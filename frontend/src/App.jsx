import { useEffect, useMemo, useRef, useState } from "react";
import {
  Search,
  FileText,
  AlertTriangle,
  Loader2,
  Database,
  Globe,
  PackageSearch,
  BarChart3,
  ShieldAlert,
  Download,
} from "lucide-react";

const API_URL =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.PROD ? "/api/generate" : "http://127.0.0.1:8000/api/generate");

const CANDIDATES_API_URL =
  import.meta.env.VITE_CANDIDATES_API_URL ||
  (import.meta.env.PROD
    ? "/api/candidates"
    : "http://127.0.0.1:8000/api/candidates");

const INTERNET_API_URL =
  import.meta.env.VITE_INTERNET_API_URL ||
  (import.meta.env.PROD ? "/api/internet" : "http://127.0.0.1:8000/api/internet");

function downloadJson(data, filename = "result.json") {
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

function downloadCsv(rows, filename = "evidences.csv") {
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

function buildEvidenceFileUrl(ev, filePath) {
  const raw = String(filePath ?? "").trim();
  if (!raw) return null;

  if (/^https?:\/\//i.test(raw)) return raw;

  const cleanPath = raw.replace(/^\/+/, "");
  const sourceName = String(ev?.source_name || "");

  if (sourceName === "etender.uzex.uz") return `https://etender.uzex.uz/${cleanPath}`;
  if (sourceName.startsWith("xarid.uzex.uz")) return `https://xarid.uzex.uz/${cleanPath}`;

  return `/${cleanPath}`;
}

function formatCandidateLabel(candidate) {
  const name = String(candidate?.name || "").trim();
  const category = String(candidate?.category_name || "").trim();

  if (name && category && normalizeText(name) !== normalizeText(category)) {
    return `${name} - ${category}`;
  }

  return name || category || "—";
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
        deal_cost_sum: 0,
        deal_cost_known: 0,
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

    if (isFiniteNumber(ev?.deal_cost)) {
      item.deal_cost_sum += ev.deal_cost;
      item.deal_cost_known += 1;
    }

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
              <th>Parametrlar</th>
              <th>Manba</th>
              <th>Lot</th>
              <th>Sana</th>
              <th>Buyurtmachi</th>
              <th>Yetkazib beruvchi</th>
              <th>Ishtirokchi</th>
              <th>Status</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((ev, index) => {
              const participantsText =
                ev?.participants_count === null || ev?.participants_count === undefined
                  ? "—"
                  : String(ev.participants_count);

              const contractUrl = buildEvidenceFileUrl(ev, ev?.contract_file_path);
              const protocolUrl = buildEvidenceFileUrl(ev, ev?.additional_protocol_file_path);

              return (
                <tr key={index}>
                  <td className="desc-cell">
                    {ev?.condition ? <pre className="param-pre">{ev.condition}</pre> : "—"}
                  </td>
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
                  <td>{formatDate(ev?.deal_date)}</td>
                  <td>{ev?.customer_name || "—"}</td>
                  <td>{ev?.provider_name || "—"}</td>
                  <td>{participantsText}</td>
                  <td>
                    <div className="status-cell">
                      <div>{ev?.deal_status_name || "—"}</div>
                      {ev?.payment_status && <div className="muted">{ev.payment_status}</div>}
                    </div>
                  </td>
                  <td>
                    <div className="file-row">
                      {ev?.source_url ? (
                        <a href={ev.source_url} target="_blank" rel="noreferrer" className="file-open">
                          Lot
                        </a>
                      ) : (
                        <span className="muted">—</span>
                      )}
                      {contractUrl && (
                        <a
                          href={contractUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="file-open"
                          title={ev?.contract_file_name || "Shartnoma fayli"}
                        >
                          Shartnoma
                        </a>
                      )}
                      {protocolUrl && (
                        <a
                          href={protocolUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="file-open"
                          title={ev?.additional_protocol_file_name || "Qo‘shimcha bayonnoma"}
                        >
                          Protokol
                        </a>
                      )}
                    </div>
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

function VariantBlock({ title, variant }) {
  if (!variant) {
    return (
      <Card className="full">
        <h3>{title}</h3>
        <p className="muted">MaвЂ™lumot yoвЂq</p>
      </Card>
    );
  }

  const description = String(variant?.description || "").trim();
  const technicalParameters = Array.isArray(variant?.technical_parameters)
    ? variant.technical_parameters.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const extraEntries = Object.entries(variant).filter(
    ([key, value]) => key !== "description" && key !== "technical_parameters" && value
  );

  return (
    <Card className="full">
      <h3>{title}</h3>
      {description ? <p>{description}</p> : null}
      {technicalParameters.length > 0 ? (
        <>
          <h4 style={{ marginTop: 16, marginBottom: 10 }}>Texnik parametrlar</h4>
          <ul className="nice-list">
            {technicalParameters.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted">MaвЂ™lumot yoвЂq</p>
      )}
      {extraEntries.length > 0 ? (
        <div className="object-list" style={{ marginTop: 16 }}>
          {extraEntries.map(([key, value]) => (
            <div className="object-row" key={key}>
              <b>{key}</b>
              <span>
                {Array.isArray(value)
                  ? value.join("; ")
                  : typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value || "вЂ”")}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function SourceStatusCard({ sourceStatus }) {
  if (!sourceStatus || Object.keys(sourceStatus).length === 0) return null;

  return (
    <Card className="full compact-card">
      <SectionTitle icon={<Database size={18} />} title="Manbalar holati" />
      <div className="source-status-grid">
        {Object.entries(sourceStatus).map(([source, info]) => {
          const status = info?.status || "unknown";
          const count = info?.count ?? 0;

          return (
            <div key={source} className="source-status-item">
              <div className="source-status-top">
                <span className="source-status-name">{source}</span>
                <span className={`status-badge ${status}`}>{status}</span>
              </div>
              <div className="source-status-bottom">
                <span className="muted tiny">Evidence: {count}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function TechnicalTask({ task }) {
  if (!task) return null;

  return (
    <div className="result-grid">
      <Card className="full">
        <SectionTitle icon={<FileText size={22} />} title="Texnik topshiriq" />
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

      <VariantBlock title="Ekonom variant" variant={task.econom_variant} />
      <VariantBlock title="Standart variant" variant={task.standard_variant} />
      <VariantBlock title="Premium variant" variant={task.premium_variant} />

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

function InternetAnswer({ result, technicalChips, onClose }) {
  const task = result?.technical_task;
  const selected = result?.selected_product;
  if (!task) return null;

  const spec = task?.recommended_specification;
  const subject =
    selected?.name ||
    (spec && typeof spec === "object" ? spec["Xarid predmeti"] : null) ||
    task?.title ||
    result?.query ||
    "Natija";

  const intro =
    String(task?.product_understanding || "").trim() ||
    String(task?.previous_tender_insights || "").trim() ||
    "";

  const specTech =
    spec && typeof spec === "object" && Array.isArray(spec["Texnik talablar"])
      ? spec["Texnik talablar"]
      : [];

  const bulletsBase = specTech.length > 0 ? specTech : Array.isArray(technicalChips) ? technicalChips : [];
  const bullets = bulletsBase
    .map((t) => String(t || "").trim())
    .filter(Boolean)
    .slice(0, 12);

  const priceSummary = task?.price_summary || result?.price_analysis || null;
  const hasPrice =
    priceSummary &&
    (typeof priceSummary?.recommended_min_price === "number" ||
      typeof priceSummary?.recommended_max_price === "number" ||
      typeof priceSummary?.avg_price === "number");

  const nf = new Intl.NumberFormat("uz-UZ");

  return (
    <Card className="internet-answer full">
      <div className="internet-answer-top">
        <div className="internet-query">
          <span className="internet-pill">"{result?.query || "so‘rov"}"</span>
          <span className="muted tiny">Internet</span>
        </div>
        <button type="button" className="secondary-btn small" onClick={onClose}>
          Yopish
        </button>
      </div>

      <h2 className="internet-title">{subject}</h2>

      {intro ? <p className="internet-intro">{intro}</p> : <p className="muted">Ma’lumot yo‘q</p>}

      {bullets.length > 0 && (
        <>
          <h3 className="internet-h3">Asosiy xarakteristikalar</h3>
          <ul className="internet-bullets">
            {bullets.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </>
      )}

      {hasPrice && (
        <div className="internet-price">
          <div className="internet-price-row">
            <span className="muted">Tavsiya narx diapazoni:</span>
            <b>
              {typeof priceSummary?.recommended_min_price === "number"
                ? nf.format(priceSummary.recommended_min_price)
                : "—"}
              {"  "}
              —
              {"  "}
              {typeof priceSummary?.recommended_max_price === "number"
                ? nf.format(priceSummary.recommended_max_price)
                : "—"}
            </b>
          </div>
          {typeof priceSummary?.avg_price === "number" && (
            <div className="muted tiny">O‘rtacha: {nf.format(priceSummary.avg_price)}</div>
          )}
        </div>
      )}
    </Card>
  );
}

function parseGroundedInternetAnswerText(text) {
  const lines = String(text || "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  if (!lines.length) return { intro: "", bullets: [] };

  const headingIndex = lines.findIndex((l) =>
    /(asosiy\s+xarakteristikalar|asosiy\s+xususiyatlar|основн(ые|ая)\s+характеристик(и|а))/i.test(
      l
    )
  );

  if (headingIndex === -1) {
    return { intro: lines.join(" "), bullets: [] };
  }

  const intro = lines.slice(0, headingIndex).join(" ").trim();
  const rest = lines.slice(headingIndex + 1);
  const bullets = rest
    .filter((l) => /^[-•*\u2022]/.test(l) || /^\d+[.)]/.test(l))
    .map((l) =>
      l
        .replace(/^[-•*\u2022]\s*/, "")
        .replace(/^\d+[.)]\s*/, "")
        .trim()
    )
    .filter(Boolean)
    .slice(0, 12);

  return { intro, bullets };
}

function GroundedInternetAnswer({ internet, loading, error, onClose }) {
  const queryText = String(internet?.query || "").trim() || "so'rov";
  const answerText = String(internet?.answer_text || "").trim();
  const sources = Array.isArray(internet?.sources) ? internet.sources : [];
  const provider = String(internet?.provider || "").trim().toLowerCase();
  const isCyrillicQuery = /[\u0400-\u04FF]/.test(queryText);
  const providerLabel =
    provider === "openrouter"
      ? isCyrillicQuery
        ? "Интернет?поиск (AI)"
        : "Internet qidiruvi (AI)"
      : provider === "free_search"
        ? isCyrillicQuery
          ? "Интернет?поиск (бесплатно)"
          : "Internet qidiruvi (bepul)"
        : "Internet qidiruvi";
  const parsed = parseGroundedInternetAnswerText(answerText);

  return (
    <Card className="internet-answer full">
      <div className="internet-answer-top">
        <div className="internet-query">
          <span className="internet-pill">"{queryText}"</span>
          <span className="muted tiny">{providerLabel}</span>
        </div>
        <button type="button" className="secondary-btn small" onClick={onClose}>
          Yopish
        </button>
      </div>

      <h2 className="internet-title">{queryText}</h2>

      {loading ? (
        <div className="loading-box" style={{ marginTop: 0 }}>
          <Loader2 className="spin" size={22} />
          <span>Internetdan ma'lumot olinmoqda...</span>
        </div>
      ) : error ? (
        <div className="error-box" style={{ marginTop: 0 }}>
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      ) : (
        <>
          {parsed.intro ? (
            <p className="internet-intro">{parsed.intro}</p>
          ) : answerText ? (
            <p className="internet-intro">{answerText}</p>
          ) : (
            <p className="muted">Ma'lumot yo'q</p>
          )}

          {parsed.bullets.length > 0 && (
            <>
              <h3 className="internet-h3">Asosiy xarakteristikalar</h3>
              <ul className="internet-bullets">
                {parsed.bullets.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </>
          )}

          {sources.length > 0 && (
            <>
              <h3 className="internet-h3">Manbalar</h3>
              <ul className="internet-bullets">
                {sources.map((s, idx) => {
                  const title = String(s?.title || "").trim();
                  const uri = String(s?.uri || "").trim();
                  if (!uri) return null;
                  return (
                    <li key={uri || `${idx}`}>
                      <a href={uri} target="_blank" rel="noreferrer">
                        {title || uri}
                      </a>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </>
      )}
    </Card>
  );
}

const SOURCE_PROGRESS_LABELS = {
  "xarid.uzex.uz": "xarid.uzex.uz completed deals",
  "xarid.uzex.uz/national": "xarid.uzex.uz national",
  "xarid.uzex.uz/auction": "xarid.uzex.uz auction",
  "etender.uzex.uz": "etender.uzex.uz",
};

function buildCandidateProgressSteps() {
  return [
    "So'rov tekshirilmoqda...",
    "Mahsulot turi aniqlanmoqda...",
    "Qidiruv rejasi tuzilmoqda...",
    "Qidiruv kalit so'zlari tayyorlanmoqda...",
    "Xarid katalog kategoriyalari tekshirilmoqda...",
    "Katalog bo'yicha mos kandidatlar qidirilmoqda...",
    "Topilgan kandidatlar score qilinmoqda...",
    "Candidate ro'yxati tayyorlanmoqda...",
  ];
}

function buildGenerateProgressSteps(enabledSources, selectedCount) {
  const selectedPrefix =
    selectedCount > 1
      ? `${selectedCount} ta kandidat uchun manbalar tayyorlanmoqda...`
      : "Tanlangan kandidat uchun manbalar tayyorlanmoqda...";

  const sourceSteps = (Array.isArray(enabledSources) ? enabledSources : [])
    .map((source) => SOURCE_PROGRESS_LABELS[source] || source)
    .filter(Boolean)
    .map((label) => `${label} dan lotlar va parametrlar olinmoqda...`);

  return [
    selectedPrefix,
    "Topilgan lotlar birlashtirilmoqda...",
    ...sourceSteps,
    "Tender parametrlaridan texnik belgilar ajratilmoqda...",
    "Narxlar tahlil qilinmoqda...",
    "LLM uchun kontekst tayyorlanmoqda...",
    "Texnik topshiriq generatsiya qilinmoqda...",
    "Natija formatlanmoqda...",
  ];
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
  const [progressSteps, setProgressSteps] = useState([]);
  const [progressIndex, setProgressIndex] = useState(0);
  const [progressElapsedSeconds, setProgressElapsedSeconds] = useState(0);
  const [error, setError] = useState("");
  const [candidateResult, setCandidateResult] = useState(null);
  const [result, setResult] = useState(null);
  const [activeTab, setActiveTab] = useState("result");
  const [activeEvidenceSource, setActiveEvidenceSource] = useState("all");
  const [supplierViewer, setSupplierViewer] = useState(null);
  const [showInternetAnswer, setShowInternetAnswer] = useState(false);
  const [internetLoading, setInternetLoading] = useState(false);
  const [internetError, setInternetError] = useState("");
  const [internetResult, setInternetResult] = useState(null);
  const internetPanelRef = useRef(null);
  const internetAbortRef = useRef(null);
  const progressStepTimerRef = useRef(null);
  const progressElapsedTimerRef = useRef(null);

  function toggleSource(source) {
    setEnabledSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]
    );
  }

  function stopProgress() {
    if (progressStepTimerRef.current) {
      clearInterval(progressStepTimerRef.current);
      progressStepTimerRef.current = null;
    }
    if (progressElapsedTimerRef.current) {
      clearInterval(progressElapsedTimerRef.current);
      progressElapsedTimerRef.current = null;
    }
    setStep("");
    setProgressSteps([]);
    setProgressIndex(0);
    setProgressElapsedSeconds(0);
  }

  function startProgress(steps, delayMs = 1800) {
    stopProgress();

    const normalized = Array.from(
      new Set(
        (Array.isArray(steps) ? steps : [])
          .map((item) => String(item || "").trim())
          .filter(Boolean)
      )
    );

    if (!normalized.length) return;

    setProgressSteps(normalized);
    setProgressIndex(0);
    setProgressElapsedSeconds(0);
    setStep(normalized[0]);

    progressElapsedTimerRef.current = setInterval(() => {
      setProgressElapsedSeconds((prev) => prev + 1);
    }, 1000);

    if (normalized.length === 1) return;

    let currentIndex = 0;
    progressStepTimerRef.current = setInterval(() => {
      currentIndex = Math.min(currentIndex + 1, normalized.length - 1);
      setProgressIndex(currentIndex);
      setStep(normalized[currentIndex]);

      if (currentIndex >= normalized.length - 1 && progressStepTimerRef.current) {
        clearInterval(progressStepTimerRef.current);
        progressStepTimerRef.current = null;
      }
    }, delayMs);
  }

  useEffect(() => {
    if (!showInternetAnswer) return;
    const node = internetPanelRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [showInternetAnswer, internetLoading]);

  useEffect(() => () => stopProgress(), []);

  async function performSearch({ openInternetAfter = false } = {}) {
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
    setCandidateResult(null);
    setResult(null);
    setShowInternetAnswer(false);
    setActiveTab("result");
    setActiveEvidenceSource("all");
    startProgress(buildCandidateProgressSteps(), 1600);

    try {
      const response = await fetch(CANDIDATES_API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          enabled_sources: enabledSources,
          max_candidates: 15,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        const detail = data?.detail;
        const message =
          typeof detail === "string"
            ? detail
            : detail && typeof detail === "object" && typeof detail.message === "string"
              ? detail.message
              : "Backend xatolik qaytardi.";
        throw new Error(message);
      }

      const list = Array.isArray(data?.candidates) ? data.candidates : [];
      const normalized = { ...data, candidates: list };
      setCandidateResult(normalized);
      return normalized;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
      stopProgress();
    }
  }

  async function performGenerate({ openInternetAfter = false, candidateSnapshot = null } = {}) {
    if (!query.trim()) {
      setError("Mahsulot nomini kiriting.");
      return;
    }

    if (!enabledSources?.length) {
      setError("Kamida bitta tender manbasini tanlang.");
      return;
    }

    const currentCandidateResult = candidateSnapshot || candidateResult;
    const candidates = Array.isArray(currentCandidateResult?.candidates)
      ? currentCandidateResult.candidates
      : [];
    const selectedCandidates = candidates.filter(Boolean);
    const selectedCandidate = selectedCandidates[0] || null;

    setLoading(true);
    setError("");
    setResult(null);
    setShowInternetAnswer(false);
    setActiveTab("result");
    setActiveEvidenceSource("all");
    startProgress(buildGenerateProgressSteps(enabledSources, selectedCandidates.length), 1800);

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
          selected_candidate: selectedCandidate,
          selected_candidates: selectedCandidates,
          candidates,
          keywords: currentCandidateResult?.keywords,
          search_plan: currentCandidateResult?.search_plan,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        const detail = data?.detail;
        const message =
          typeof detail === "string"
            ? detail
            : detail && typeof detail === "object" && typeof detail.message === "string"
              ? detail.message
              : "Backend xatolik qaytardi.";
        throw new Error(message);
      }

      setResult(data);
      setActiveTab("result");
      if (openInternetAfter && data?.technical_task) setShowInternetAnswer(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      stopProgress();
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const candidateData = await performSearch();
    if (candidateData) {
      await performGenerate({ candidateSnapshot: candidateData });
    }
  }

  async function performInternetSearch() {
    const q = String(query || "").trim();

    setShowInternetAnswer(true);

    if (!q) {
      setInternetError("Mahsulot yoki xizmat nomini kiriting.");
      return;
    }

    if (internetAbortRef.current) {
      internetAbortRef.current.abort();
    }

    const controller = new AbortController();
    internetAbortRef.current = controller;

    setInternetLoading(true);
    setInternetError("");
    setInternetResult({ query: q, answer_text: "", sources: [] });

    try {
      const response = await fetch(INTERNET_API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        signal: controller.signal,
        body: JSON.stringify({ query: q }),
      });

      const data = await response.json();

      if (!response.ok) {
        const detail = data?.detail;
        let message = "Backend xatolik qaytardi.";
        if (typeof detail === "string") {
          message = detail;
        } else if (detail && typeof detail === "object") {
          const m = typeof detail.message === "string" ? detail.message.trim() : "";
          if (m) message = m;
        }
        throw new Error(message);
      }

      setInternetResult(data);
    } catch (err) {
      if (err?.name === "AbortError") {
        return;
      }
      setInternetError(err.message);
    } finally {
      if (internetAbortRef.current === controller) {
        internetAbortRef.current = null;
        setInternetLoading(false);
      }
    }
  }

  const selectedProducts = useMemo(() => {
    const list = Array.isArray(result?.selected_products) ? result.selected_products.filter(Boolean) : [];
    if (list.length > 0) return list;
    return result?.selected_product ? [result.selected_product] : [];
  }, [result]);
  const selected = selectedProducts[0] || null;
  const candidates = result?.candidates || [];
  const candidateConfidence = result?.candidate_confidence || null;
  const evidences = result?.evidences || [];
  const sourceStatus = result?.source_status || {};
  const searchPlan = result?.search_plan || candidateResult?.search_plan || null;

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
  const searchKeywords = useMemo(() => {
    const fromPlan = [
      ...(Array.isArray(searchPlan?.search_keywords_ru) ? searchPlan.search_keywords_ru : []),
      ...(Array.isArray(searchPlan?.search_keywords_uz) ? searchPlan.search_keywords_uz : []),
    ];
    const fallback = Array.isArray(result?.keywords)
      ? result.keywords
      : Array.isArray(candidateResult?.keywords)
        ? candidateResult.keywords
        : [];

    return Array.from(
      new Set(
        [...fromPlan, ...fallback]
          .map((item) => String(item || "").trim())
          .filter(Boolean)
      )
    ).slice(0, 12);
  }, [searchPlan, result?.keywords, candidateResult?.keywords]);
  const excludeKeywords = useMemo(() => {
    const list = Array.isArray(searchPlan?.exclude_keywords_ru) ? searchPlan.exclude_keywords_ru : [];
    return Array.from(new Set(list.map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 8);
  }, [searchPlan]);

  const alternativeCandidates = useMemo(() => {
    const list = Array.isArray(candidates) ? candidates : [];
    const selectedCodes = new Set(
      selectedProducts
        .map((item) => String(item?.product_code || "").trim())
        .filter(Boolean)
    );
    return list
      .filter((c) => {
        const code = String(c?.product_code || "").trim();
        return code && !selectedCodes.has(code);
      })
      .slice(0, 8);
  }, [candidates, selectedProducts]);

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

  const sortedEvidencesForActiveSource = useMemo(
    () => sortEvidences(evidencesForActiveSource, "date_desc"),
    [evidencesForActiveSource]
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
                  label="Bitimlar soni"
                  value={`${supplierViewer.total_deals} ta`}
                  hint="Topilgan evidencelar soni"
                />
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
                  label="Umumiy summa"
                  value={
                    supplierViewer.deal_cost_known > 0
                      ? new Intl.NumberFormat("uz-UZ").format(supplierViewer.deal_cost_sum)
                      : "—"
                  }
                  hint={
                    supplierViewer.deal_cost_known > 0
                      ? `${supplierViewer.deal_cost_known} ta bitimda deal_cost bor`
                      : "deal_cost ko‘rsatilmagan"
                  }
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
                      const contractUrl = buildEvidenceFileUrl(ev, ev?.contract_file_path);
                      const protocolUrl = buildEvidenceFileUrl(ev, ev?.additional_protocol_file_path);

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
                            <div className="file-row">
                              {ev?.source_url ? (
                                <a href={ev.source_url} target="_blank" rel="noreferrer" className="file-open">
                                  Lot
                                </a>
                              ) : (
                                <span className="muted">—</span>
                              )}
                              {contractUrl && (
                                <a
                                  href={contractUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="file-open"
                                  title={ev?.contract_file_name || "Shartnoma fayli"}
                                >
                                  Shartnoma
                                </a>
                              )}
                              {protocolUrl && (
                                <a
                                  href={protocolUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="file-open"
                                  title={ev?.additional_protocol_file_name || "Qo‘shimcha bayonnoma"}
                                >
                                  Protokol
                                </a>
                              )}
                            </div>
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
        <h1>AI yordamida xarid texnik topshirig‘i</h1>
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
              <div className="sources-internet-btn">
                <button
                  type="button"
                  className="secondary-btn small"
                  onClick={performInternetSearch}
                  disabled={!query.trim()}
                  title={
                    !query.trim()
                      ? "Mahsulot nomini kiriting."
                      : undefined
                  }
                >
                  <Globe size={16} />
                  Internet
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
          <div className="loading-box" style={{ alignItems: "flex-start" }}>
            <Loader2 className="spin" size={22} />
            <div style={{ display: "grid", gap: 8, width: "100%" }}>
              <span>{step || "Ishlanmoqda..."}</span>
              {progressSteps.length > 0 && (
                <>
                  <span className="muted tiny">
                    {Math.min(progressIndex + 1, progressSteps.length)} / {progressSteps.length} bosqich ·{" "}
                    {progressElapsedSeconds}s
                  </span>
                  <div style={{ display: "grid", gap: 6 }}>
                    {progressSteps.map((item, idx) => {
                      const status = idx < progressIndex ? "done" : idx === progressIndex ? "active" : "pending";
                      const marker = status === "done" ? "✓" : status === "active" ? "•" : "○";

                      return (
                        <div
                          key={`${item}_${idx}`}
                          style={{
                            display: "flex",
                            gap: 8,
                            alignItems: "flex-start",
                            opacity: status === "pending" ? 0.72 : 1,
                          }}
                        >
                          <span className="muted tiny">{marker}</span>
                          <span
                            className={status === "pending" ? "muted tiny" : "tiny"}
                            style={{ lineHeight: 1.45, fontWeight: status === "active" ? 600 : 400 }}
                          >
                            {item}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="error-box">
            <AlertTriangle size={20} />
            <span>{error}</span>
          </div>
        )}
      </Card>

      {showInternetAnswer && (
        <div ref={internetPanelRef}>
          <GroundedInternetAnswer
            internet={internetResult}
            loading={internetLoading}
            error={internetError}
            onClose={() => setShowInternetAnswer(false)}
          />
        </div>
      )}

      {false && !loading && candidateResult && !result && (
        <Card className="full">
          <SectionTitle
            icon={<PackageSearch size={22} />}
            title="Alternative candidates"
            subtitle="Xarid katalogidan topilgan variantlardan bir yoki bir nechtasini tanlang"
          />

          {Array.isArray(candidateResult?.candidates) && candidateResult.candidates.length > 0 ? (
            <>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  alignItems: "center",
                  marginTop: 12,
                  flexWrap: "wrap",
                }}
              >
                <span className="muted">
                  Tanlangan kandidatlar: <b>{selectedCandidateCodes.length}</b>
                </span>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() =>
                      setSelectedCandidateCodes(
                        candidateResult.candidates
                          .map((item) => String(item?.product_code || "").trim())
                          .filter(Boolean)
                      )
                    }
                  >
                    Hammasini tanlash
                  </button>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => setSelectedCandidateCodes([])}
                  >
                    Tozalash
                  </button>
                </div>
              </div>

              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Tanlash</th>
                      <th>Katalog nomi</th>
                      <th>Kategoriya</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidateResult.candidates.map((c) => {
                      const code = String(c?.product_code || "").trim();
                      const checked = code && selectedCandidateCodes.includes(code);
                      return (
                        <tr key={code || JSON.stringify(c)}>
                          <td>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleCandidateSelection(code)}
                            />
                          </td>
                          <td>
                            <div style={{ display: "grid", gap: 4 }}>
                              <strong>{String(c?.name || "").trim() || "—"}</strong>
                              <div className="muted tiny">
                                <code>{code || "—"}</code>
                              </div>
                            </div>
                          </td>
                          <td>{String(c?.category_name || "").trim() || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <p className="muted" style={{ marginTop: 12 }}>
                Hech narsa tanlanmasa, tizim eng mos kandidatni avtomatik tanlaydi.
              </p>

              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => performGenerate()}
                >
                  <FileText size={20} />
                  Tanlash va davom etish
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="muted">Candidate topilmadi. Davom etib tahlil qilish mumkin.</p>
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
                <button type="button" className="primary-btn" onClick={() => performGenerate()}>
                  <FileText size={20} />
                  Davom etish
                </button>
              </div>
            </>
          )}
        </Card>
      )}

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

          {activeTab === "result" && (
            <>
              <div className="summary-grid">
                <Card>
                  <SectionTitle
                    icon={<PackageSearch size={22} />}
                    title="Qidiruv rejasi"
                    subtitle="LLM mahsulotni qanday tushundi"
                  />
                  <div className="object-list">
                    <div className="object-row">
                      <b>Mahsulot turi</b>
                      <span>{searchPlan?.detected_item_type || "—"}</span>
                    </div>
                    <div className="object-row">
                      <b>Brand / model</b>
                      <span>
                        {[searchPlan?.brand, searchPlan?.model]
                          .map((item) => String(item || "").trim())
                          .filter(Boolean)
                          .join(" / ") || "—"}
                      </span>
                    </div>
                    <div className="object-row">
                      <b>Izoh</b>
                      <span>{searchPlan?.notes || "—"}</span>
                    </div>
                  </div>
                  {searchKeywords.length > 0 && (
                    <div className="chips" style={{ marginTop: 12 }}>
                      {searchKeywords.map((keyword) => (
                        <span key={keyword}>{keyword}</span>
                      ))}
                    </div>
                  )}
                  {excludeKeywords.length > 0 && (
                    <div className="object-list" style={{ marginTop: 12 }}>
                      <div className="object-row">
                        <b>Exclude</b>
                        <span>{excludeKeywords.join(", ")}</span>
                      </div>
                    </div>
                  )}
                </Card>

                {alternativeCandidates.length > 0 && (
                  <Card className="full compact-card">
                    <SectionTitle
                      icon={<PackageSearch size={22} />}
                      title="Alternative candidates"
                      subtitle="Xarid katalogidan topilgan boshqa variantlar"
                    />

                    {(candidateConfidence || candidates.length > 0) && (
                      <div className="stats-grid">
                        <StatCard
                          label="Candidate soni"
                          value={candidateConfidence.candidate_count ?? candidates.length}
                        />
                        <StatCard
                          label="Tanlangan"
                          value={candidateConfidence?.selected_count ?? selectedProducts.length}
                        />
                      </div>
                    )}

                    {alternativeCandidates.length > 0 ? (
                      <div className="table-wrap" style={{ marginTop: 12 }}>
                        <table>
                          <thead>
                            <tr>
                              <th>Katalog nomi</th>
                              <th>Kategoriya</th>
                            </tr>
                          </thead>
                          <tbody>
                            {alternativeCandidates.map((c) => (
                              <tr key={c.product_code}>
                                <td>
                                  <div style={{ display: "grid", gap: 4 }}>
                                    <strong>{String(c?.name || "").trim() || "—"}</strong>
                                    <div className="muted tiny">
                                      <code>{c.product_code}</code>
                                    </div>
                                  </div>
                                </td>
                                <td>{String(c?.category_name || "").trim() || "—"}</td>
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
              </div>

              <TechnicalTask task={result.technical_task} />

              <Card className="full">
                <SectionTitle
                  icon={<Database size={22} />}
                  title="Tender parametrlari (jadval)"
                  subtitle="Har bir lot bo‘yicha yig‘ilgan parametrlar (ketma-ket)"
                />
                <EvidenceTable evidences={evidences} />
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
                </Card>
              )}
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
                          <th>Unit soni</th>
                          <th>Umumiy summa</th>
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
                              <td>
                                {row.deal_cost_known > 0
                                  ? new Intl.NumberFormat("uz-UZ").format(row.deal_cost_sum)
                                  : "—"}
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
            <div className="result-grid">
              <SourceStatusCard sourceStatus={sourceStatus} />
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
                <EvidenceTable evidences={sortedEvidencesForActiveSource} />
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  );
}

