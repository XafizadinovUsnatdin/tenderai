import { useMemo, useState } from "react";
import {
  Search,
  FileText,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Database,
  PackageSearch,
  BarChart3,
  ShieldAlert,
  Download,
} from "lucide-react";

const API_URL = "http://127.0.0.1:8000/api/generate";

function getDefaultEvidenceFilters() {
  return {
    searchText: "",
    region: "all",
    status: "all",
    providerText: "",
    dateFrom: "",
    dateTo: "",
    sortBy: "date_desc",
  };
}

function downloadJson(data, filename = "tenderai_result.json") {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();

  URL.revokeObjectURL(url);
}

function downloadCsv(rows, filename = "tenderai_evidences.csv") {
  const data = Array.isArray(rows) ? rows : [];

  const headers = [
    "source_name",
    "lot_display_no",
    "lot_id",
    "product_name",
    "category_name",
    "deal_date",
    "region",
    "customer_name",
    "customer_inn",
    "provider_name",
    "provider_inn",
    "participants_count",
    "currency",
    "deal_status_name",
    "payment_status",
    "source_url",
    "contract_file_name",
    "contract_file_path",
    "additional_protocol_file_name",
    "additional_protocol_file_path",
  ];

  function esc(value) {
    const s = String(value ?? "");
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  }

  const lines = [];
  lines.push(headers.join(","));

  for (const row of data) {
    const values = headers.map((h) => esc(row?.[h]));
    lines.push(values.join(","));
  }

  const csv = "\ufeff" + lines.join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();

  URL.revokeObjectURL(url);
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function normalizeText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function parseDateSafe(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function parseDateInput(value) {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function buildFileUrl(sourceName, filePath) {
  if (!filePath) return null;
  const raw = String(filePath);
  if (/^https?:\/\//i.test(raw)) return raw;
  if (sourceName === "etender.uzex.uz") {
    return `https://etender.uzex.uz/${raw.replace(/^\/+/, "")}`;
  }
  return raw;
}

function evText(ev) {
  return normalizeText(
    [
      ev?.source_name,
      ev?.source_type,
      ev?.lot_display_no,
      ev?.product_name,
      ev?.category_name,
      ev?.customer_name,
      ev?.customer_inn,
      ev?.provider_name,
      ev?.provider_inn,
      ev?.region,
      ev?.deal_status_name,
      ev?.payment_status,
      ev?.condition,
      ev?.contract_file_name,
      ev?.contract_file_path,
      ev?.additional_protocol_file_name,
      ev?.additional_protocol_file_path,
    ]
      .filter(Boolean)
      .join(" | ")
  );
}

function buildEvidenceFilterOptions(evidences) {
  const regions = new Set();
  const statuses = new Set();

  for (const ev of evidences || []) {
    if (ev?.region) regions.add(ev.region);
    if (ev?.deal_status_name) statuses.add(ev.deal_status_name);
  }

  return {
    regions: Array.from(regions).sort((a, b) => String(a).localeCompare(String(b))),
    statuses: Array.from(statuses).sort((a, b) => String(a).localeCompare(String(b))),
  };
}

function applyEvidenceFilters(evidences, filters) {
  const list = Array.isArray(evidences) ? evidences : [];

  const q = normalizeText(filters?.searchText);
  const providerQ = normalizeText(filters?.providerText);
  const region = filters?.region || "all";
  const status = filters?.status || "all";

  const from = parseDateInput(filters?.dateFrom);
  const to = parseDateInput(filters?.dateTo);

  const filtered = list.filter((ev) => {
    if (q && !evText(ev).includes(q)) return false;

    if (providerQ) {
      const providerText = normalizeText(
        [ev?.provider_name, ev?.provider_inn].filter(Boolean).join(" ")
      );
      if (!providerText.includes(providerQ)) return false;
    }

    if (region !== "all" && (ev?.region || "") !== region) return false;
    if (status !== "all" && (ev?.deal_status_name || "") !== status) return false;

    const d = parseDateSafe(ev?.deal_date);
    if (from && (!d || d < from)) return false;
    if (to) {
      const toEnd = new Date(to);
      toEnd.setHours(23, 59, 59, 999);
      if (!d || d > toEnd) return false;
    }

    return true;
  });

  const sortBy = filters?.sortBy || "date_desc";
  return sortEvidences(filtered, sortBy);
}

function sortEvidences(evidences, sortBy) {
  const rows = Array.isArray(evidences) ? [...evidences] : [];

  function t(ev) {
    const d = parseDateSafe(ev?.deal_date);
    return d ? d.getTime() : 0;
  }

  const cmp = (a, b) => {
    switch (sortBy) {
      case "date_asc":
        return t(a) - t(b);
      default:
        return t(b) - t(a);
    }
  };

  rows.sort(cmp);
  return rows;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString("uz-UZ");
}

const SUCCESS_STATUS_HINTS = [
  "оплач", // Оплачено/Оплачена
  "постав", // Поставлена/Поставлено
  "выполн",
  "принят",
  "qabul",
  "amalga",
  "yetkazib",
  "shartnoma tuzil",
  "g'olib",
  "golib",
];

const RISK_STATUS_HINTS = [
  "отмен",
  "аннул",
  "не состоя",
  "неисполн",
  "rad",
  "bekor",
  "muvaffaqiyatsiz",
  "jarima",
  "штраф",
];

function classifyEvidenceOutcome(ev) {
  const status = normalizeText(ev?.deal_status_name);
  const payment = normalizeText(ev?.payment_status);
  const text = `${status} ${payment}`.trim();

  if (!text) return "unknown";
  if (RISK_STATUS_HINTS.some((h) => text.includes(h))) return "risky";
  if (SUCCESS_STATUS_HINTS.some((h) => text.includes(h))) return "success";
  return "unknown";
}

function mostCommonKey(counts) {
  let bestKey = null;
  let bestCount = 0;
  for (const [key, count] of counts.entries()) {
    if (count > bestCount) {
      bestKey = key;
      bestCount = count;
    }
  }
  return bestKey;
}

function computeSupplierRiskLabel(stats) {
  const total = stats.total_deals || 0;
  if (total <= 0) return "—";

  const riskyRate = stats.risky_deals / total;
  const singleBidderRate = stats.total_deals > 0 ? stats.single_bidder_deals / stats.total_deals : 0;

  const riskScore = riskyRate * 75 + singleBidderRate * 25;

  if (riskScore >= 35) return "Yuqori";
  if (riskScore >= 15) return "O‘rta";
  return "Past";
}

function computeSupplierRating(stats) {
  const total = stats.total_deals || 0;
  if (total <= 0) return null;

  const successRate = stats.success_deals / total;
  const riskyRate = stats.risky_deals / total;
  const unknownRate = stats.unknown_deals / total;
  const singleBidderRate = stats.total_deals > 0 ? stats.single_bidder_deals / stats.total_deals : 0;

  let score = 0;

  // Success vs risk
  score += successRate * 50;
  score += (1 - riskyRate) * 25;
  score += (1 - unknownRate) * 10;
  score += (1 - singleBidderRate) * 10;

  // Experience bonus
  score += Math.min(5, Math.log10(total + 1) * 5);

  return Math.max(0, Math.min(100, Math.round(score)));
}

function buildSupplierPerformance(evidences) {
  const list = Array.isArray(evidences) ? evidences : [];

  const grouped = new Map();

  for (const ev of list) {
    const providerNameRaw = String(ev?.provider_name || "").trim();
    const providerInnRaw = String(ev?.provider_inn || "").trim();
    const providerName = providerNameRaw || "Noma’lum";
    const key = `${providerName}||${providerInnRaw}`;

    const item =
      grouped.get(key) || {
        key,
        provider_name: providerName,
        provider_inn: providerInnRaw || null,
        total_deals: 0,
        success_deals: 0,
        risky_deals: 0,
        unknown_deals: 0,
        unit_sum: 0,
        unit_sum_known: 0,
        single_bidder_deals: 0,
        last_date: null,
        regions: new Set(),
        categories: new Map(),
        deals: [],
      };

    item.total_deals += 1;
    item.deals.push(ev);

    const outcome = classifyEvidenceOutcome(ev);
    if (outcome === "success") item.success_deals += 1;
    else if (outcome === "risky") item.risky_deals += 1;
    else item.unknown_deals += 1;

    if (isFiniteNumber(ev?.amount)) {
      item.unit_sum += ev.amount;
      item.unit_sum_known += 1;
    }

    if (ev?.region) item.regions.add(ev.region);

    const category = String(ev?.category_name || ev?.product_name || "—").trim();
    if (category) item.categories.set(category, (item.categories.get(category) || 0) + 1);

    if (Number(ev?.participants_count) === 1) item.single_bidder_deals += 1;

    const date = parseDateSafe(ev?.deal_date);
    if (date) {
      if (!item.last_date || date > item.last_date) item.last_date = date;
    }

    grouped.set(key, item);
  }

  const rows = [];

  for (const item of grouped.values()) {
    const mainCategory = mostCommonKey(item.categories);
    const rating = computeSupplierRating(item);
    const riskLabel = computeSupplierRiskLabel(item);
    const dealsSorted = [...item.deals].sort((a, b) => {
      const da = parseDateSafe(a?.deal_date);
      const db = parseDateSafe(b?.deal_date);
      if (!da && !db) return 0;
      if (!da) return 1;
      if (!db) return -1;
      return db.getTime() - da.getTime();
    });

    rows.push({
      ...item,
      main_category: mainCategory,
      rating,
      risk: riskLabel,
      last_date: item.last_date ? item.last_date.toISOString() : null,
      regions: Array.from(item.regions),
      deals_sorted: dealsSorted,
    });
  }

  rows.sort((a, b) => {
    const ra = typeof a.rating === "number" ? a.rating : -1;
    const rb = typeof b.rating === "number" ? b.rating : -1;
    if (rb !== ra) return rb - ra;
    if (b.success_deals !== a.success_deals) return b.success_deals - a.success_deals;
    return b.total_deals - a.total_deals;
  });

  return rows;
}

function extractTechnicalHighlights(evidences, limit = 20) {
  const text = (evidences || [])
    .map((ev) => ev?.condition || "")
    .filter(Boolean)
    .join("\n");

  const counts = new Map();

  function add(token, weight = 1) {
    const clean = String(token || "").replace(/\s+/g, " ").trim();
    if (!clean) return;
    counts.set(clean, (counts.get(clean) || 0) + weight);
  }

  // Network / switch patterns
  for (const match of text.matchAll(/\b(\d{1,2})\s*(?:port|ports|порт|порта)\b/gi)) {
    add(`${match[1]} port`);
  }
  if (/\bRJ-?45\b/i.test(text)) add("RJ45", 3);
  if (/\bPoE\+?\b/i.test(text)) add("PoE", 3);
  if (/\bSFP\+?\b/i.test(text)) add("SFP", 2);
  if (/\b(10\s*\/\s*100\s*\/\s*1000)\b/i.test(text)) add("10/100/1000 Mbps", 3);
  if (/\b(10\s*\/\s*100)\b/i.test(text)) add("10/100 Mbps", 2);
  if (/\b(gigabit|гигабит)\b/i.test(text)) add("Gigabit", 2);
  if (/\b(ethernet|ethernet\+?)\b/i.test(text)) add("Ethernet");
  if (/\bplug\s*and\s*play\b/i.test(text)) add("Plug and Play");

  // Common IT terms
  if (/\bwi-?fi\b/i.test(text) || /\bwifi\b/i.test(text)) add("Wi-Fi", 3);
  if (/\bbluetooth\b/i.test(text)) add("Bluetooth");
  if (/\bUSB\b/i.test(text)) add("USB");
  if (/\bHDMI\b/i.test(text)) add("HDMI");
  if (/\bVGA\b/i.test(text)) add("VGA");
  if (/\bdisplayport\b/i.test(text)) add("DisplayPort");

  // Paper / printer patterns
  if (/\bA4\b/i.test(text)) add("A4");
  if (/\bA3\b/i.test(text)) add("A3");
  for (const match of text.matchAll(/\b(\d{3,4})\s*dpi\b/gi)) {
    add(`${match[1]} DPI`, 2);
  }
  for (const match of text.matchAll(/\b(\d{1,3})\s*(?:ppm|стр\/мин)\b/gi)) {
    add(`${match[1]} ppm`);
  }

  // Monitor patterns
  for (const match of text.matchAll(/\b(\d{3,4})\s*[xх]\s*(\d{3,4})\b/g)) {
    add(`${match[1]}x${match[2]}`, 2);
  }
  for (const match of text.matchAll(/\b(\d{1,2}(?:\.\d)?)\s*(?:\"|inch|дюйм)\b/gi)) {
    add(`${match[1]}\"`, 2);
  }
  for (const match of text.matchAll(/\b(\d{2,3})\s*hz\b/gi)) {
    add(`${match[1]} Hz`, 2);
  }

  // Generic numeric units
  for (const match of text.matchAll(/\b(\d{1,4})\s*(gb|tb)\b/gi)) {
    add(`${match[1]} ${match[2].toUpperCase()}`);
  }
  for (const match of text.matchAll(/\b(\d{1,4})\s*(?:w|вт)\b/gi)) {
    add(`${match[1]} W`);
  }

  if (/\b(metall|металл)\b/i.test(text)) add("Metall korpus");
  if (/\b(kafolat|kafolati|garant|гарант)\b/i.test(text)) add("Kafolat", 2);

  return Array.from(counts.entries())
    .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]))
    .map(([token]) => token)
    .slice(0, limit);
}

function Tabs({ value, onChange, items }) {
  return (
    <div className="tabs">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className={`tab-btn ${value === item.key ? "active" : ""}`}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function EvidenceFilters({ value, onChange, options, totalCount, filteredCount, onReset, onDownloadCsv }) {
  const regions = options?.regions || [];
  const statuses = options?.statuses || [];

  return (
    <div className="evidence-tools">
      <div className="evidence-tools-top">
        <div className="evidence-summary">
          Ko‘rsatilmoqda: <b>{filteredCount}</b> / {totalCount}
        </div>
        <div className="evidence-actions">
          <button
            type="button"
            className="secondary-btn small"
            onClick={onDownloadCsv}
            disabled={!filteredCount}
          >
            CSV yuklab olish
          </button>
          <button type="button" className="secondary-btn small" onClick={onReset}>
            Filtrlarni tozalash
          </button>
        </div>
      </div>

      <div className="filters-grid">
        <div className="filter-group wide">
          <label>Qidiruv</label>
          <input
            value={value.searchText}
            onChange={(e) => onChange({ ...value, searchText: e.target.value })}
            placeholder="Lot, mahsulot, buyurtmachi, provider, INN, status..."
          />
        </div>

        <div className="filter-group">
          <label>Region</label>
          <select
            value={value.region}
            onChange={(e) => onChange({ ...value, region: e.target.value })}
          >
            <option value="all">Barchasi</option>
            {regions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Status</label>
          <select
            value={value.status}
            onChange={(e) => onChange({ ...value, status: e.target.value })}
          >
            <option value="all">Barchasi</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Provider</label>
          <input
            value={value.providerText}
            onChange={(e) => onChange({ ...value, providerText: e.target.value })}
            placeholder="Nom yoki INN"
          />
        </div>

        <div className="filter-group">
          <label>From</label>
          <input
            type="date"
            value={value.dateFrom}
            onChange={(e) => onChange({ ...value, dateFrom: e.target.value })}
          />
        </div>

        <div className="filter-group">
          <label>To</label>
          <input
            type="date"
            value={value.dateTo}
            onChange={(e) => onChange({ ...value, dateTo: e.target.value })}
          />
        </div>

        <div className="filter-group">
          <label>Saralash</label>
          <select
            value={value.sortBy}
            onChange={(e) => onChange({ ...value, sortBy: e.target.value })}
          >
            <option value="date_desc">Sana (yangi → eski)</option>
            <option value="date_asc">Sana (eski → yangi)</option>
          </select>
        </div>
      </div>
    </div>
  );
}

function EvidenceTable({ evidences }) {
  const rows = evidences || [];

  if (rows.length === 0) {
    return <p className="muted">Evidence topilmadi</p>;
  }

  return (
    <>
      <div className="table-wrap">
        <table className="evidence-table">
          <thead>
            <tr>
              <th>Manba</th>
              <th>Lot</th>
              <th>Mahsulot / Kategoriya</th>
              <th>Sana</th>
              <th>Buyurtmachi</th>
              <th>Yetkazib beruvchi</th>
              <th>Ishtirokchi</th>
              <th>Hujjatlar</th>
              <th>Status</th>
              <th>Link</th>
              <th>Parametrlar</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((ev, index) => {
            const name = ev?.product_name || ev?.category_name || "—";
            const participantsText =
              ev?.participants_count === null || ev?.participants_count === undefined
                ? "—"
                : String(ev.participants_count);

            const contractHref = buildFileUrl(ev?.source_name, ev?.contract_file_path);
            const protocolHref = buildFileUrl(ev?.source_name, ev?.additional_protocol_file_path);
            const protocolName =
              ev?.additional_protocol_file_name ||
              (ev?.additional_protocol_file_path
                ? String(ev.additional_protocol_file_path).split("/").pop()
                : null);
            const contractName =
              ev?.contract_file_name ||
              (ev?.contract_file_path ? String(ev.contract_file_path).split("/").pop() : null);

            return (
              <tr key={index}>
                <td>
                  <div className="source-cell">
                    <span>{ev?.source_name || "—"}</span>
                    {ev?.source_type && <span className="muted tiny">{ev.source_type}</span>}
                  </div>
                </td>
                <td>
                  <div className="lot-cell">
                    <div>{ev?.lot_display_no || "—"}</div>
                    {ev?.lot_id !== null && ev?.lot_id !== undefined && (
                      <div className="muted tiny">ID: {String(ev.lot_id)}</div>
                    )}
                  </div>
                </td>
                <td>{name}</td>
                <td>{formatDate(ev?.deal_date)}</td>
                <td>{ev?.customer_name || "—"}</td>
                <td>{ev?.provider_name || "—"}</td>
                <td>{participantsText}</td>
                <td>
                  <div className="files-cell">
                    {(ev?.additional_protocol_file_name || ev?.additional_protocol_file_path) ? (
                      <div className="file-row">
                        <span className="file-label">Bayonnoma:</span>
                        <span className="file-name" title={ev?.additional_protocol_file_path || ""}>
                          {protocolName || "—"}
                        </span>
                        {protocolHref ? (
                          <a className="file-open" href={protocolHref} target="_blank" rel="noreferrer">
                            Ochish
                          </a>
                        ) : (
                          <span className="muted tiny">—</span>
                        )}
                      </div>
                    ) : (
                      <div className="muted tiny">Bayonnoma: —</div>
                    )}

                    {(ev?.contract_file_name || ev?.contract_file_path) ? (
                      <div className="file-row">
                        <span className="file-label">Shartnoma:</span>
                        <span className="file-name" title={ev?.contract_file_path || ""}>
                          {contractName || "—"}
                        </span>
                        {contractHref ? (
                          <a className="file-open" href={contractHref} target="_blank" rel="noreferrer">
                            Ochish
                          </a>
                        ) : (
                          <span className="muted tiny">—</span>
                        )}
                      </div>
                    ) : (
                      <div className="muted tiny">Shartnoma: —</div>
                    )}
                  </div>
                </td>
                <td>
                  <div className="status-cell">
                    <div>{ev?.deal_status_name || "—"}</div>
                    {ev?.payment_status && <div className="muted">{ev.payment_status}</div>}
                  </div>
                </td>
                <td>
                  {ev?.source_url ? (
                    <a href={ev.source_url} target="_blank" rel="noreferrer">
                      Ochish
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="desc-cell">
                  {ev?.condition ? <pre className="param-pre">{ev.condition}</pre> : "—"}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Card({ children, className = "" }) {
  return <div className={`card ${className}`}>{children}</div>;
}

function SectionTitle({ icon, title, subtitle }) {
  return (
    <div className="section-title">
      <div className="section-icon">{icon}</div>
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
    </div>
  );
}

function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card">
      <p>{label}</p>
      <h3>{value}</h3>
      {hint && <span>{hint}</span>}
    </div>
  );
}

function ListBlock({ items }) {
  if (!items) return <p className="muted">Ma’lumot yo‘q</p>;

  if (Array.isArray(items)) {
    return (
      <ul className="nice-list">
        {items.map((item, index) => (
          <li key={index}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
        ))}
      </ul>
    );
  }

  if (typeof items === "object") {
    return (
      <div className="object-list">
        {Object.entries(items).map(([key, value]) => (
          <div className="object-row" key={key}>
            <b>{key}</b>
            <span>
              {Array.isArray(value)
                ? value.join("; ")
                : typeof value === "object"
                  ? JSON.stringify(value)
                  : value || "—"}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return <p>{items}</p>;
}

function TechnicalTask({ task }) {
  if (!task) return null;

  return (
    <div className="result-grid">
      <Card className="full">
        <SectionTitle
          icon={<FileText size={22} />}
          title={task.title || "Texnik topshiriq"}
          subtitle="AI tomonidan yig‘ilgan dalillar asosida tayyorlangan draft"
        />
      </Card>

      <Card>
        <h3>Mahsulot tushunchasi</h3>
        <p>{task.product_understanding || "Ma’lumot yo‘q"}</p>
      </Card>

      <Card>
        <h3>Oldingi tenderlar xulosasi</h3>
        <p>{task.previous_tender_insights || "Ma’lumot yo‘q"}</p>
      </Card>

      <Card className="full">
        <h3>Tavsiya etilgan texnik topshiriq</h3>
        <ListBlock items={task.recommended_specification} />
      </Card>

      <Card>
        <h3>Ekonom variant</h3>
        <ListBlock items={task.econom_variant} />
      </Card>

      <Card>
        <h3>Standart variant</h3>
        <ListBlock items={task.standard_variant} />
      </Card>

      <Card>
        <h3>Premium variant</h3>
        <ListBlock items={task.premium_variant} />
      </Card>

      <Card>
        <h3>Risk ogohlantirishlari</h3>
        <ListBlock items={task.risk_warnings} />
      </Card>

      <Card>
        <h3>Manba asosidagi izohlar</h3>
        <ListBlock items={task.source_based_notes} />
      </Card>
    </div>
  );
}

export default function App() {
  const [query, setQuery] = useState("TP-Link TL-SG108S");
  const [periodMonths, setPeriodMonths] = useState(12);
  const [enabledSources, setEnabledSources] = useState([
    "xarid.uzex.uz",
    "xarid.uzex.uz/national",
    "xarid.uzex.uz/auction",
    "etender.uzex.uz",
  ]);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [activeTab, setActiveTab] = useState("result");
  const [activeEvidenceSource, setActiveEvidenceSource] = useState("all");
  const [evidenceFilters, setEvidenceFilters] = useState(() => getDefaultEvidenceFilters());
  const [supplierViewer, setSupplierViewer] = useState(null);

  function toggleSource(source) {
    setEnabledSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]
    );
  }

  async function handleSubmit(e) {
    e.preventDefault();

    if (!query.trim()) {
      setError("Mahsulot nomini kiriting.");
      return;
    }

    if (!enabledSources?.length) {
      setError("Kamida bitta tender manbasini tanlang.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setActiveTab("result");
    setActiveEvidenceSource("all");
    setEvidenceFilters(getDefaultEvidenceFilters());

    const fakeSteps = [
      "Mahsulot turi aniqlanmoqda...",
      "Xarid.uzex katalogidan product_code qidirilmoqda...",
      "Tender manbalaridan dalillar yig‘ilmoqda...",
      "Texnik topshiriq generatsiya qilinmoqda...",
    ];

    let index = 0;
    setStep(fakeSteps[index]);

    const timer = setInterval(() => {
      index = Math.min(index + 1, fakeSteps.length - 1);
      setStep(fakeSteps[index]);
    }, 2500);

    try {
      const response = await fetch(API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          period_months: Number(periodMonths),
          enabled_sources: enabledSources,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Backend xatolik qaytardi.");
      }

      setResult(data);
      setActiveTab("result");
      setStep("Tayyor");
    } catch (err) {
      setError(err.message);
      setStep("");
    } finally {
      clearInterval(timer);
      setLoading(false);
    }
  }

  const selected = result?.selected_product;
  const candidates = result?.candidates || [];
  const candidateConfidence = result?.candidate_confidence || null;
  const evidences = result?.evidences || [];

  const supplierRows = useMemo(
    () => buildSupplierPerformance(evidences),
    [evidences]
  );
  const technicalHighlights = useMemo(() => extractTechnicalHighlights(evidences), [evidences]);
  const technicalParams = useMemo(() => {
    const params = result?.technical_task?.recommended_specification?.["Texnik talablar"];
    return Array.isArray(params) ? params.filter(Boolean).slice(0, 20) : [];
  }, [result]);
  const technicalChips = useMemo(() => {
    const merged = [...technicalParams, ...technicalHighlights].map((t) => String(t || "").trim()).filter(Boolean);
    return Array.from(new Set(merged)).slice(0, 28);
  }, [technicalParams, technicalHighlights]);

  const alternativeCandidates = useMemo(() => {
    const list = Array.isArray(candidates) ? candidates : [];
    const selectedCode = selected?.product_code;
    return list.filter((c) => c?.product_code && c.product_code !== selectedCode).slice(0, 8);
  }, [candidates, selected?.product_code]);

  const auditFlags = useMemo(() => {
    const list = Array.isArray(evidences) ? evidences : [];
    const participantsOne = [];

    for (const ev of list) {
      const participants = ev?.participants_count;
      if (participants !== null && participants !== undefined && Number(participants) === 1) {
        participantsOne.push(ev);
      }
    }

    return {
      participantsOne,
    };
  }, [evidences]);

  const tabItems = useMemo(() => {
    const count = evidences.length;
    return [
      { key: "result", label: "Natija" },
      { key: "analytics", label: "Analitika" },
      { key: "evidences", label: `Manbalar (${count})` },
    ];
  }, [result, evidences.length]);

  const evidencesBySource = result?.evidences_by_source || {};

  const evidenceTabItems = useMemo(() => {
    const allCount = evidences.length;
    const keys = Object.keys(evidencesBySource || {});
    const preferredOrder = [
      "xarid.uzex.uz",
      "xarid.uzex.uz/national",
      "xarid.uzex.uz/auction",
      "etender.uzex.uz",
    ];

    const ordered = [];

    for (const k of preferredOrder) {
      if (keys.includes(k)) ordered.push(k);
    }

    for (const k of keys) {
      if (!ordered.includes(k)) ordered.push(k);
    }

    const sourceItems = ordered.map((source) => ({
      key: source,
      label: `${source} (${(evidencesBySource[source] || []).length})`,
    }));

    return [{ key: "all", label: `All (${allCount})` }, ...sourceItems];
  }, [evidences.length, evidencesBySource]);

  const evidencesForActiveSource = useMemo(() => {
    if (activeEvidenceSource === "all") return evidences;

    const bySource = evidencesBySource?.[activeEvidenceSource];
    if (Array.isArray(bySource)) return bySource;

    return evidences.filter((ev) => ev?.source_name === activeEvidenceSource);
  }, [activeEvidenceSource, evidences, evidencesBySource]);

  const evidenceFilterOptions = useMemo(
    () => buildEvidenceFilterOptions(evidencesForActiveSource),
    [evidencesForActiveSource]
  );

  const filteredEvidencesForActiveSource = useMemo(
    () => applyEvidenceFilters(evidencesForActiveSource, evidenceFilters),
    [evidencesForActiveSource, evidenceFilters]
  );

  return (
    <div className="app">
      {supplierViewer && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          onClick={() => setSupplierViewer(null)}
        >
          <div className="modal-card modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <div className="modal-title">{supplierViewer?.provider_name || "Yetkazib beruvchi"}</div>
                <div className="modal-subtitle">
                  {[
                    supplierViewer?.provider_inn ? `INN: ${supplierViewer.provider_inn}` : null,
                    supplierViewer?.risk ? `Risk: ${supplierViewer.risk}` : null,
                    typeof supplierViewer?.rating === "number" ? `Reyting: ${supplierViewer.rating}/100` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </div>
              <button type="button" className="modal-close" onClick={() => setSupplierViewer(null)}>
                Yopish
              </button>
            </div>

            <div className="modal-body">
              <div className="stats-grid">
                <StatCard
                  label="Muvaffaqiyatli bitimlar"
                  value={`${supplierViewer.success_deals} ta`}
                  hint="Status bo‘yicha soddalashtirilgan tasnif"
                />
                <StatCard
                  label="Riskli / bekor"
                  value={`${supplierViewer.risky_deals} ta`}
                  hint="Bekor/Rad/Jarima va h.k."
                />
                <StatCard
                  label="Unit (ma’lum)"
                  value={
                    supplierViewer.unit_sum_known > 0
                      ? `${new Intl.NumberFormat("uz-UZ").format(supplierViewer.unit_sum)} dona`
                      : "—"
                  }
                  hint={
                    supplierViewer.unit_sum_known > 0
                      ? `${supplierViewer.unit_sum_known} ta bitimda amount bor`
                      : "Etender’da amount yo‘q bo‘lishi mumkin"
                  }
                />
                <StatCard
                  label="Asosiy kategoriya"
                  value={supplierViewer.main_category || "—"}
                />
                <StatCard
                  label="Oxirgi savdo"
                  value={formatDate(supplierViewer.last_date)}
                />
                <StatCard
                  label="Yakka qatnashchi"
                  value={`${supplierViewer.single_bidder_deals || 0} ta`}
                  hint="participants_count = 1 bo‘lgan holatlar"
                />
              </div>

              <p className="muted supplier-note">
                Reyting va risk — faqat ochiq tender ma’lumotlari asosida hisoblangan indikator.
                Yetkazib berish sifati, kechikish, jarima va shikoyat kabi ichki ma’lumotlar bo‘lmasa,
                bu ko‘rsatkichlar 100% kafolat bermaydi.
              </p>

              <div className="table-wrap">
                <table className="supplier-history">
                  <thead>
                    <tr>
                      <th>Sana</th>
                      <th>Manba</th>
                      <th>Lot</th>
                      <th>Mahsulot</th>
                      <th>Buyurtmachi</th>
                      <th>Status</th>
                      <th>Link</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(supplierViewer.deals_sorted || []).slice(0, 50).map((ev, idx) => {
                      const outcome = classifyEvidenceOutcome(ev);
                      const outcomeLabel =
                        outcome === "success" ? "Muvaffaqiyatli" : outcome === "risky" ? "Riskli" : "Noma’lum";
                      const badgeClass = outcome === "success" ? "badge ok" : outcome === "risky" ? "badge bad" : "badge";

                      return (
                        <tr key={`${ev?.lot_display_no || "lot"}_${idx}`}>
                          <td>{formatDate(ev?.deal_date)}</td>
                          <td>{ev?.source_name || "—"}</td>
                          <td>{ev?.lot_display_no || "—"}</td>
                          <td>{ev?.product_name || ev?.category_name || "—"}</td>
                          <td>{ev?.customer_name || "—"}</td>
                          <td>
                            <div className="status-cell">
                              <div className={badgeClass}>{outcomeLabel}</div>
                              <div className="muted tiny">{ev?.deal_status_name || "—"}</div>
                            </div>
                          </td>
                          <td>
                            {ev?.source_url ? (
                              <a href={ev.source_url} target="_blank" rel="noreferrer">
                                Ochish
                              </a>
                            ) : (
                              "—"
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="hero">
        <div className="hero-badge">
          <Database size={16} />
          TenderAI
        </div>

        <h1>AI yordamida xarid texnik topshirig‘i</h1>
        <p>
          Mahsulot yoki xizmat nomini kiriting. Tizim xarid.uzex.uz (completed deals)
          va etender.uzex.uz (deals list) manbalaridan dalillarni yig‘adi va texnik
          topshiriq draftini yaratadi.
        </p>
      </div>

      <Card className="search-card">
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="input-group main-input">
              <label>Mahsulot yoki xizmat nomi</label>
              <div className="input-wrap">
                <Search size={20} />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Masalan: TP-Link TL-SG108S, printer, konditsioner..."
                />
              </div>
            </div>

            <div className="input-group period-input">
              <label>Tahlil davri</label>
              <select
                value={periodMonths}
                onChange={(e) => setPeriodMonths(e.target.value)}
              >
                <option value={3}>Oxirgi 3 oy</option>
                <option value={6}>Oxirgi 6 oy</option>
                <option value={12}>Oxirgi 12 oy</option>
                <option value={24}>Oxirgi 24 oy</option>
                <option value={36}>Oxirgi 36 oy</option>
                <option value={48}>Oxirgi 48 oy</option>
              </select>
            </div>

            <div className="input-group sources-input">
              <label>Manbalar</label>
              <div className="source-checks">
                <label className="source-check">
                  <input
                    type="checkbox"
                    checked={enabledSources.includes("xarid.uzex.uz")}
                    onChange={() => toggleSource("xarid.uzex.uz")}
                  />
                  <span>xarid.uzex.uz</span>
                </label>
                <label className="source-check">
                  <input
                    type="checkbox"
                    checked={enabledSources.includes("xarid.uzex.uz/national")}
                    onChange={() => toggleSource("xarid.uzex.uz/national")}
                  />
                  <span>xarid.uzex.uz (national)</span>
                </label>
                <label className="source-check">
                  <input
                    type="checkbox"
                    checked={enabledSources.includes("xarid.uzex.uz/auction")}
                    onChange={() => toggleSource("xarid.uzex.uz/auction")}
                  />
                  <span>xarid.uzex.uz (auction)</span>
                </label>
                <label className="source-check">
                  <input
                    type="checkbox"
                    checked={enabledSources.includes("etender.uzex.uz")}
                    onChange={() => toggleSource("etender.uzex.uz")}
                  />
                  <span>etender.uzex.uz</span>
                </label>
              </div>
              <div className="source-presets">
                <button
                  type="button"
                  className="secondary-btn small"
                  onClick={() =>
                    setEnabledSources([
                      "xarid.uzex.uz",
                      "xarid.uzex.uz/national",
                      "xarid.uzex.uz/auction",
                      "etender.uzex.uz",
                    ])
                  }
                >
                  Hammasi
                </button>
                <button
                  type="button"
                  className="secondary-btn small"
                  onClick={() => setEnabledSources(["xarid.uzex.uz", "xarid.uzex.uz/national"])}
                >
                  Xarid (shop+national)
                </button>
                <button
                  type="button"
                  className="secondary-btn small"
                  onClick={() => setEnabledSources(["etender.uzex.uz", "xarid.uzex.uz/auction"])}
                >
                  Audit
                </button>
              </div>
            </div>
            <button className="primary-btn" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="spin" size={20} />
                  Ishlanmoqda
                </>
              ) : (
                <>
                  <PackageSearch size={20} />
                  Qidirish
                </>
              )}
            </button>
          </div>
        </form>

        {loading && (
          <div className="loading-box">
            <Loader2 className="spin" size={22} />
            <span>{step}</span>
          </div>
        )}

        {error && (
          <div className="error-box">
            <AlertTriangle size={20} />
            <span>{error}</span>
          </div>
        )}
      </Card>

      {result && (
        <>
          <div className="result-header">
            <Tabs value={activeTab} onChange={setActiveTab} items={tabItems} />
            <div className="top-actions">
              <button
                className="secondary-btn"
                onClick={() => downloadJson(result, `${query}_result.json`)}
              >
                <Download size={18} />
                JSON yuklab olish
              </button>
              <button
                className="secondary-btn"
                onClick={() => downloadJson(result?.evidences || [], `${query}_evidences.json`)}
              >
                <Download size={18} />
                Evidences JSON
              </button>
              <button
                className="secondary-btn"
                onClick={() => downloadJson(result?.technical_task || {}, `${query}_technical_task.json`)}
              >
                <Download size={18} />
                Texnik topshiriq JSON
              </button>
            </div>
          </div>

          {result?.source_status && (
            <Card className="full">
              <SectionTitle
                icon={<Database size={22} />}
                title="Manbalar holati"
                subtitle="Har bir tender portali bo‘yicha qisqa natija"
              />
              <div className="table-wrap">
                <table className="source-status-table">
                  <thead>
                    <tr>
                      <th>Manba</th>
                      <th>Status</th>
                      <th>Evidence</th>
                      <th>Xabar</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(result.source_status).map(([source, info]) => {
                      const status = info?.status || "unknown";
                      const count = info?.count ?? 0;
                      const message = info?.message;

                      return (
                        <tr key={source}>
                          <td>{source}</td>
                          <td>
                            <span className={`status-badge ${status}`}>{status}</span>
                          </td>
                          <td>{count}</td>
                          <td className="muted">{message || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {activeTab === "result" && (
            <>
              <div className="summary-grid">
                <Card>
                  <SectionTitle
                    icon={<CheckCircle2 size={22} />}
                    title="Tanlangan mahsulot"
                    subtitle="Xarid katalogidan eng mos product_code"
                  />
                  <div className="product-box">
                    <h3>{selected?.name}</h3>
                    <p>{selected?.category_name}</p>
                    <code>{selected?.product_code}</code>
                  </div>
                </Card>

                <Card>
                  <SectionTitle
                    icon={<PackageSearch size={22} />}
                    title="Qidiruv rejasi"
                    subtitle="LLM mahsulotni qanday tushundi"
                  />
                  <div className="chips">
                    {result.keywords?.map((k) => (
                      <span key={k}>{k}</span>
                    ))}
                  </div>
                </Card>

                {Array.isArray(candidates) && candidates.length > 0 && (
                  <Card className="full">
                    <SectionTitle
                      icon={<PackageSearch size={22} />}
                      title="Alternative candidates"
                      subtitle="Xarid katalogidan topilgan boshqa variantlar"
                    />

                    {candidateConfidence && (
                      <div className="stats-grid">
                        <StatCard
                          label="Candidate soni"
                          value={candidateConfidence.candidate_count ?? candidates.length}
                        />
                        <StatCard
                          label="Tanlangan rank"
                          value={candidateConfidence.selected_rank ?? "—"}
                          hint="1 = eng yuqori score"
                        />
                        <StatCard
                          label="Top-2 score farqi"
                          value={
                            typeof candidateConfidence.score_gap_top_vs_second === "number"
                              ? candidateConfidence.score_gap_top_vs_second.toFixed(2)
                              : "—"
                          }
                          hint="Katta bo‘lsa, tanlov aniqroq"
                        />
                      </div>
                    )}

                    {alternativeCandidates.length > 0 ? (
                      <div className="table-wrap" style={{ marginTop: 12 }}>
                        <table>
                          <thead>
                            <tr>
                              <th>product_code</th>
                              <th>Nomi</th>
                              <th>Kategoriya</th>
                              <th>Score</th>
                            </tr>
                          </thead>
                          <tbody>
                            {alternativeCandidates.map((c) => (
                              <tr key={c.product_code}>
                                <td>
                                  <code>{c.product_code}</code>
                                </td>
                                <td>{c.name || "—"}</td>
                                <td>{c.category_name || "—"}</td>
                                <td>
                                  {typeof c.score === "number" ? c.score.toFixed(2) : String(c.score ?? "—")}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="muted">Alternative candidate topilmadi</p>
                    )}
                  </Card>
                )}

                <Card className="full">
                  <SectionTitle
                    icon={<FileText size={22} />}
                    title="Texnik parametrlar summary"
                    subtitle="Tender tavsiflaridan ajratilgan ko‘p uchragan talablar"
                  />
                  {technicalChips.length > 0 ? (
                    <div className="chips">
                      {technicalChips.map((t) => (
                        <span key={t}>{t}</span>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">Ma’lumot yo‘q</p>
                  )}
                </Card>

                {auditFlags.participantsOne.length > 0 && (
                  <Card className="warning-card full">
                    <SectionTitle
                      icon={<ShieldAlert size={22} />}
                      title="Audit: Red flags"
                      subtitle="Bu xulosa emas — tekshiruv uchun signal (evidence asosida)"
                    />

                    <div className="stats-grid">
                      <StatCard
                        label="Qatnashchi = 1"
                        value={auditFlags.participantsOne.length}
                        hint="participants_count = 1 bo‘lgan bitimlar"
                      />
                      <StatCard
                        label="Eslatma"
                        value="Qo‘lda tekshiring"
                        hint="Tender konteksti muhim"
                      />
                    </div>

                    {auditFlags.participantsOne.length > 0 && (
                      <>
                        <h3 style={{ marginTop: 16 }}>Qatnashchi = 1 bo‘lgan bitimlar</h3>
                        <div className="table-wrap">
                          <table>
                            <thead>
                              <tr>
                                <th>Manba</th>
                                <th>Lot</th>
                                <th>Mahsulot</th>
                                <th>Status</th>
                                <th>Link</th>
                              </tr>
                            </thead>
                            <tbody>
                              {auditFlags.participantsOne.slice(0, 10).map((ev, idx) => (
                                <tr key={`${ev?.source_name}-${ev?.lot_display_no}-${idx}`}>
                                  <td>{ev?.source_name || "—"}</td>
                                  <td>{ev?.lot_display_no || "—"}</td>
                                  <td>{ev?.product_name || ev?.category_name || "—"}</td>
                                  <td>{ev?.deal_status_name || "—"}</td>
                                  <td>
                                    {ev?.source_url ? (
                                      <a href={ev.source_url} target="_blank" rel="noreferrer">
                                        Ochish
                                      </a>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </Card>
                )}

                <Card className="full">
                  <SectionTitle
                    icon={<CheckCircle2 size={22} />}
                    title="Nega shu mahsulot tanlandi?"
                    subtitle="Candidate tanlash sababi"
                  />
                  <p>
                    {result.candidate_selection_reason ||
                      selected?.selection_reason ||
                      "Ma’lumot yo‘q"}
                  </p>
                </Card>
              </div>

              <Card className="full">
                <SectionTitle
                  icon={<Database size={22} />}
                  title="Tender parametrlari (jadval)"
                  subtitle="Har bir lot bo‘yicha yig‘ilgan parametrlar va hujjat linklari"
                />
                <EvidenceTable evidences={evidences} />
              </Card>

              {result.validation_warnings?.length > 0 && (
                <Card className="warning-card">
                  <SectionTitle
                    icon={<AlertTriangle size={22} />}
                    title="Validator ogohlantirishlari"
                    subtitle="LLM javobida tekshirilishi kerak bo‘lgan joylar"
                  />
                  <ul className="nice-list">
                    {result.validation_warnings.map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </Card>
              )}

              <TechnicalTask task={result.technical_task} />
            </>
          )}

          {activeTab === "analytics" && (
            <div className="result-grid">
              <Card className="full">
                <SectionTitle
                  icon={<BarChart3 size={22} />}
                  title="Yetkazib beruvchi reytingi"
                  subtitle="Bitimlar soni, status va risk indikatori (ochiq ma’lumotlar asosida)"
                />
                {supplierRows.length > 0 ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Firma</th>
                          <th>Muvaffaqiyatli</th>
                          <th>Riskli</th>
                          <th>Bitimlar</th>
                          <th>Yakka</th>
                          <th>Unit (ma’lum)</th>
                          <th>Asosiy kategoriya</th>
                          <th>Risk</th>
                          <th>Reyting</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {supplierRows.slice(0, 25).map((row) => {
                          const riskClass =
                            row.risk === "Past"
                              ? "badge ok"
                              : row.risk === "Yuqori"
                                ? "badge bad"
                                : row.risk === "O‘rta"
                                  ? "badge warn"
                                  : "badge";

                          return (
                            <tr key={row.key}>
                              <td>
                                <div className="supplier-cell">
                                  <button
                                    type="button"
                                    className="supplier-name-btn"
                                    onClick={() => setSupplierViewer(row)}
                                    title="Batafsil ko‘rish"
                                  >
                                    {row.provider_name}
                                  </button>
                                  {row.provider_inn && <div className="muted tiny">INN: {row.provider_inn}</div>}
                                </div>
                              </td>
                              <td>{row.success_deals}</td>
                              <td>{row.risky_deals}</td>
                              <td>{row.total_deals}</td>
                              <td>{row.single_bidder_deals || 0}</td>
                              <td>
                                {row.unit_sum_known > 0 ? new Intl.NumberFormat("uz-UZ").format(row.unit_sum) : "—"}
                              </td>
                              <td className="muted" title={row.main_category || ""}>
                                {row.main_category ? String(row.main_category).slice(0, 56) : "—"}
                              </td>
                              <td>
                                <span className={riskClass}>{row.risk}</span>
                              </td>
                              <td>{typeof row.rating === "number" ? `${row.rating}/100` : "—"}</td>
                              <td>
                                <button type="button" className="desc-btn" onClick={() => setSupplierViewer(row)}>
                                  Batafsil
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">Ma’lumot yo‘q</p>
                )}
              </Card>
            </div>
          )}

          {activeTab === "evidences" && (
            <Card className="full">
              <SectionTitle
                icon={<Database size={22} />}
                title="Evidence / Manbalar"
                subtitle="Texnik topshiriq va audit qaysi lotlarga asoslanganini ko‘rsatadi"
              />
              <Tabs
                value={activeEvidenceSource}
                onChange={setActiveEvidenceSource}
                items={evidenceTabItems}
              />
              <EvidenceFilters
                value={evidenceFilters}
                onChange={setEvidenceFilters}
                options={evidenceFilterOptions}
                totalCount={evidencesForActiveSource.length}
                filteredCount={filteredEvidencesForActiveSource.length}
                onReset={() => setEvidenceFilters(getDefaultEvidenceFilters())}
                onDownloadCsv={() =>
                  downloadCsv(
                    filteredEvidencesForActiveSource,
                    `${String(query || "query").replace(/[^\w\-]+/g, "_")}_${
                      activeEvidenceSource || "all"
                    }_evidences.csv`
                  )
                }
              />
              <EvidenceTable evidences={filteredEvidencesForActiveSource} />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
