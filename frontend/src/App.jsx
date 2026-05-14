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
    minUnitPrice: "",
    maxUnitPrice: "",
    minDealCost: "",
    maxDealCost: "",
    sortBy: "date_desc",
    onlyPriceEligible: false,
    onlyWithFiles: false,
  };
}

function formatMoney(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("uz-UZ").format(value) + " so‘m";
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
    "deal_cost",
    "unit_price",
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

function getPriceGlobal(result) {
  const pa = result?.price_analysis;
  if (!pa) return null;
  if (pa.global) return pa.global;
  return pa;
}

function getPriceBySource(result) {
  const pa = result?.price_analysis;
  if (!pa) return null;
  return pa.by_source || null;
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
  const onlyPriceEligible = Boolean(filters?.onlyPriceEligible);
  const onlyWithFiles = Boolean(filters?.onlyWithFiles);

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

    if (onlyPriceEligible && !isFiniteNumber(ev?.unit_price)) return false;

    if (onlyWithFiles) {
      const hasFiles = Boolean(
        ev?.contract_file_name ||
          ev?.contract_file_path ||
          ev?.additional_protocol_file_name ||
          ev?.additional_protocol_file_path
      );
      if (!hasFiles) return false;
    }

    const d = parseDateSafe(ev?.deal_date);
    if (from && (!d || d < from)) return false;
    if (to) {
      const toEnd = new Date(to);
      toEnd.setHours(23, 59, 59, 999);
      if (!d || d > toEnd) return false;
    }

    const minUnit = filters?.minUnitPrice;
    const maxUnit = filters?.maxUnitPrice;
    if (minUnit !== "" && minUnit !== null && minUnit !== undefined) {
      const n = Number(minUnit);
      if (Number.isFinite(n)) {
        if (!isFiniteNumber(ev?.unit_price) || ev.unit_price < n) return false;
      }
    }
    if (maxUnit !== "" && maxUnit !== null && maxUnit !== undefined) {
      const n = Number(maxUnit);
      if (Number.isFinite(n)) {
        if (!isFiniteNumber(ev?.unit_price) || ev.unit_price > n) return false;
      }
    }

    const minDeal = filters?.minDealCost;
    const maxDeal = filters?.maxDealCost;
    if (minDeal !== "" && minDeal !== null && minDeal !== undefined) {
      const n = Number(minDeal);
      if (Number.isFinite(n)) {
        if (!isFiniteNumber(ev?.deal_cost) || ev.deal_cost < n) return false;
      }
    }
    if (maxDeal !== "" && maxDeal !== null && maxDeal !== undefined) {
      const n = Number(maxDeal);
      if (Number.isFinite(n)) {
        if (!isFiniteNumber(ev?.deal_cost) || ev.deal_cost > n) return false;
      }
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

  function numOrNull(v) {
    return isFiniteNumber(v) ? v : null;
  }

  const cmp = (a, b) => {
    switch (sortBy) {
      case "date_asc":
        return t(a) - t(b);
      case "unit_price_desc": {
        const av = numOrNull(a?.unit_price);
        const bv = numOrNull(b?.unit_price);
        if (av === null && bv === null) return t(b) - t(a);
        if (av === null) return 1;
        if (bv === null) return -1;
        return bv - av;
      }
      case "unit_price_asc": {
        const av = numOrNull(a?.unit_price);
        const bv = numOrNull(b?.unit_price);
        if (av === null && bv === null) return t(b) - t(a);
        if (av === null) return 1;
        if (bv === null) return -1;
        return av - bv;
      }
      case "deal_cost_desc": {
        const av = numOrNull(a?.deal_cost);
        const bv = numOrNull(b?.deal_cost);
        if (av === null && bv === null) return t(b) - t(a);
        if (av === null) return 1;
        if (bv === null) return -1;
        return bv - av;
      }
      case "deal_cost_asc": {
        const av = numOrNull(a?.deal_cost);
        const bv = numOrNull(b?.deal_cost);
        if (av === null && bv === null) return t(b) - t(a);
        if (av === null) return 1;
        if (bv === null) return -1;
        return av - bv;
      }
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

function monthKey(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function median(values) {
  if (!values?.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

function buildMonthlyPriceSeries(evidences) {
  const byMonth = new Map();

  for (const ev of evidences || []) {
    if (!isFiniteNumber(ev?.unit_price)) continue;
    const key = monthKey(ev?.deal_date);
    if (!key) continue;

    const list = byMonth.get(key) || [];
    list.push(ev.unit_price);
    byMonth.set(key, list);
  }

  const result = [];

  for (const [month, prices] of byMonth.entries()) {
    const sorted = [...prices].sort((a, b) => a - b);
    const avg = sorted.reduce((sum, v) => sum + v, 0) / sorted.length;

    result.push({
      month,
      count: sorted.length,
      min: sorted[0],
      max: sorted[sorted.length - 1],
      avg,
      median: median(sorted),
    });
  }

  return result.sort((a, b) => a.month.localeCompare(b.month));
}

function buildGroupedPriceStats(evidences, keyFn) {
  const grouped = new Map();

  for (const ev of evidences || []) {
    if (!isFiniteNumber(ev?.unit_price)) continue;
    const key = keyFn(ev);
    if (!key) continue;

    const list = grouped.get(key) || [];
    list.push(ev.unit_price);
    grouped.set(key, list);
  }

  const rows = [];

  for (const [key, prices] of grouped.entries()) {
    const sorted = [...prices].sort((a, b) => a - b);
    const avg = sorted.reduce((sum, v) => sum + v, 0) / sorted.length;

    rows.push({
      key,
      count: sorted.length,
      avg,
      median: median(sorted),
      min: sorted[0],
      max: sorted[sorted.length - 1],
    });
  }

  return rows.sort((a, b) => b.count - a.count);
}

function extractTechnicalHighlights(evidences, limit = 12) {
  const text = (evidences || []).map((ev) => ev?.condition || "").join("\n");
  const highlights = [];

  function add(token) {
    const clean = String(token || "").trim();
    if (!clean) return;
    if (highlights.includes(clean)) return;
    highlights.push(clean);
  }

  for (const match of text.matchAll(/\b(\d{1,2})\s*(?:port|ports|порт|порта)\b/gi)) {
    add(`${match[1]} port`);
  }

  if (/\bRJ-?45\b/i.test(text)) add("RJ45");
  if (/\bPoE\b/i.test(text)) add("PoE");
  if (/\bSFP\+?\b/i.test(text)) add("SFP");
  if (/\b(10\s*\/\s*100\s*\/\s*1000)\b/i.test(text)) add("10/100/1000 Mbps");
  if (/\b(10\s*\/\s*100)\b/i.test(text)) add("10/100 Mbps");
  if (/\b(gigabit|гигабит)\b/i.test(text)) add("Gigabit");
  if (/\bplug\s*and\s*play\b/i.test(text)) add("Plug and Play");
  if (/\b(metall|металл)\b/i.test(text)) add("Metall korpus");
  if (/\b(kafolat|kafolati|garant|гарант)\b/i.test(text)) add("Kafolat");

  return highlights.slice(0, limit);
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

function LineChart({ data, series }) {
  const width = 720;
  const height = 260;
  const paddingX = 44;
  const paddingY = 26;

  const allValues = [];
  for (const row of data) {
    for (const s of series) {
      if (isFiniteNumber(row?.[s.key])) allValues.push(row[s.key]);
    }
  }

  if (!data?.length || allValues.length === 0) {
    return <p className="muted">Grafik uchun ma’lumot yetarli emas</p>;
  }

  let minVal = Math.min(...allValues);
  let maxVal = Math.max(...allValues);

  if (minVal === maxVal) {
    minVal = minVal * 0.9;
    maxVal = maxVal * 1.1;
  }

  const plotW = width - paddingX * 2;
  const plotH = height - paddingY * 2;
  const xStep = data.length > 1 ? plotW / (data.length - 1) : 0;

  const x = (idx) => paddingX + idx * xStep;
  const y = (v) => paddingY + (1 - (v - minVal) / (maxVal - minVal)) * plotH;

  const gridLines = 4;
  const grid = [];
  for (let i = 0; i <= gridLines; i++) {
    const yy = paddingY + (i / gridLines) * plotH;
    grid.push(yy);
  }

  function buildPath(key) {
    const pts = data
      .map((row, idx) => {
        const v = row?.[key];
        if (!isFiniteNumber(v)) return null;
        return { idx, v };
      })
      .filter(Boolean);

    if (pts.length === 0) return "";

    return pts
      .map((p, i) => `${i === 0 ? "M" : "L"} ${x(p.idx).toFixed(2)} ${y(p.v).toFixed(2)}`)
      .join(" ");
  }

  const first = data[0]?.month;
  const last = data[data.length - 1]?.month;

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Narx trend grafigi">
        {grid.map((yy) => (
          <line
            key={yy}
            x1={paddingX}
            x2={width - paddingX}
            y1={yy}
            y2={yy}
            stroke="rgba(148,163,184,0.35)"
            strokeWidth="1"
          />
        ))}

        {series.map((s) => (
          <path
            key={s.key}
            d={buildPath(s.key)}
            fill="none"
            stroke={s.color}
            strokeWidth={s.width ?? 2.5}
            opacity={s.opacity ?? 1}
          />
        ))}

        <text x={paddingX} y={height - 8} fontSize="12" fill="#64748b">
          {first}
        </text>
        <text x={width - paddingX} y={height - 8} fontSize="12" fill="#64748b" textAnchor="end">
          {last}
        </text>
      </svg>

      <div className="chart-legend">
        {series.map((s) => (
          <div key={s.key} className="legend-item">
            <span className="legend-dot" style={{ background: s.color }} />
            <span>{s.label}</span>
          </div>
        ))}
      </div>
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
          <label>Unit narx min</label>
          <input
            inputMode="numeric"
            value={value.minUnitPrice}
            onChange={(e) => onChange({ ...value, minUnitPrice: e.target.value })}
            placeholder="masalan 500000"
          />
        </div>

        <div className="filter-group">
          <label>Unit narx max</label>
          <input
            inputMode="numeric"
            value={value.maxUnitPrice}
            onChange={(e) => onChange({ ...value, maxUnitPrice: e.target.value })}
            placeholder="masalan 1500000"
          />
        </div>

        <div className="filter-group">
          <label>Bitim narxi min</label>
          <input
            inputMode="numeric"
            value={value.minDealCost}
            onChange={(e) => onChange({ ...value, minDealCost: e.target.value })}
            placeholder="masalan 1000000"
          />
        </div>

        <div className="filter-group">
          <label>Bitim narxi max</label>
          <input
            inputMode="numeric"
            value={value.maxDealCost}
            onChange={(e) => onChange({ ...value, maxDealCost: e.target.value })}
            placeholder="masalan 8000000"
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
            <option value="unit_price_desc">Unit narx (yuqori → past)</option>
            <option value="unit_price_asc">Unit narx (past → yuqori)</option>
            <option value="deal_cost_desc">Bitim narxi (yuqori → past)</option>
            <option value="deal_cost_asc">Bitim narxi (past → yuqori)</option>
          </select>
        </div>

        <div className="filter-group checks">
          <label>Qo‘shimcha</label>
          <div className="check-row">
            <label className="mini-check">
              <input
                type="checkbox"
                checked={value.onlyPriceEligible}
                onChange={(e) => onChange({ ...value, onlyPriceEligible: e.target.checked })}
              />
              <span>Faqat unit_price bor</span>
            </label>
            <label className="mini-check">
              <input
                type="checkbox"
                checked={value.onlyWithFiles}
                onChange={(e) => onChange({ ...value, onlyWithFiles: e.target.checked })}
              />
              <span>Faqat hujjatli</span>
            </label>
          </div>
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
            <th>Bitim narxi</th>
            <th>Unit narx</th>
            <th>Hujjatlar</th>
            <th>Status</th>
            <th>Link</th>
            <th>Tavsif</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((ev, index) => {
            const name = ev?.product_name || ev?.category_name || "—";
            const dealCostText = isFiniteNumber(ev?.deal_cost) ? formatMoney(ev.deal_cost) : "—";
            const unitPriceText = isFiniteNumber(ev?.unit_price) ? formatMoney(ev.unit_price) : "—";
            const participantsText =
              ev?.participants_count === null || ev?.participants_count === undefined
                ? "—"
                : String(ev.participants_count);

            const isEtender = ev?.source_name === "etender.uzex.uz";

            const contractHref = buildFileUrl(ev?.source_name, ev?.contract_file_path);
            const protocolHref = buildFileUrl(ev?.source_name, ev?.additional_protocol_file_path);

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
                <td>{dealCostText}</td>
                <td>
                  <div className="price-cell">
                    <div>{unitPriceText}</div>
                    {isEtender && !isFiniteNumber(ev?.unit_price) && (
                      <div className="badge muted">Unit narx yo‘q (quantity yo‘q)</div>
                    )}
                    {!isEtender && isFiniteNumber(ev?.unit_price) && (
                      <div className="muted tiny" title="unit_price = deal_cost / amount (xarid.uzex.uz)">
                        deal/amount
                      </div>
                    )}
                  </div>
                </td>
                <td>
                  <div className="files-cell">
                    {(ev?.additional_protocol_file_name || ev?.additional_protocol_file_path) ? (
                      <div className="file-row">
                        <span className="file-label">Bayonnoma:</span>{" "}
                        {protocolHref ? (
                          <a href={protocolHref} target="_blank" rel="noreferrer">
                            {ev?.additional_protocol_file_name || "Fayl"}
                          </a>
                        ) : (
                          <span>{ev?.additional_protocol_file_name || "—"}</span>
                        )}
                      </div>
                    ) : (
                      <div className="muted tiny">Bayonnoma: —</div>
                    )}

                    {(ev?.contract_file_name || ev?.contract_file_path) ? (
                      <div className="file-row">
                        <span className="file-label">Shartnoma:</span>{" "}
                        {contractHref ? (
                          <a href={contractHref} target="_blank" rel="noreferrer">
                            {ev?.contract_file_name || "Fayl"}
                          </a>
                        ) : (
                          <span>{ev?.contract_file_name || "—"}</span>
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
                  {ev?.condition ? (
                    <details>
                      <summary>Ko‘rish</summary>
                      <pre className="pre">{ev.condition}</pre>
                    </details>
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
        <h3>Narx xulosasi</h3>
        <ListBlock items={task.price_summary} />
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
      "Completed deals olinmoqda...",
      "Narx tahlili qilinmoqda...",
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

  const priceGlobal = getPriceGlobal(result);
  const priceBySource = getPriceBySource(result);
  const selected = result?.selected_product;
  const evidences = result?.evidences || [];

  const monthlySeries = useMemo(() => buildMonthlyPriceSeries(evidences), [evidences]);
  const regionStats = useMemo(
    () => buildGroupedPriceStats(evidences, (ev) => ev?.region),
    [evidences]
  );
  const providerStats = useMemo(
    () => buildGroupedPriceStats(evidences, (ev) => ev?.provider_name),
    [evidences]
  );
  const technicalHighlights = useMemo(() => extractTechnicalHighlights(evidences), [evidences]);
  const technicalParams = useMemo(() => {
    const params = result?.technical_task?.recommended_specification?.["Texnik talablar"];
    return Array.isArray(params) ? params.filter(Boolean).slice(0, 20) : [];
  }, [result]);

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
      <div className="hero">
        <div className="hero-badge">
          <Database size={16} />
          Multi-source (xarid + etender) AI generator
        </div>

        <h1>AI yordamida xarid texnik topshirig‘i</h1>
        <p>
          Mahsulot yoki xizmat nomini kiriting. Tizim xarid.uzex.uz (completed deals)
          va etender.uzex.uz (deals list) manbalaridan dalillarni yig‘adi, narxni
          (unit_price bo‘lsa) tahlil qiladi va texnik topshiriq draftini yaratadi.
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

          {result?.source_status && (
            <div className="summary-grid">
              {Object.entries(result.source_status).map(([source, info]) => {
                const status = info?.status || "unknown";
                const count = info?.count ?? 0;
                const eligible = info?.price_eligible_count ?? 0;
                const message = info?.message;

                return (
                  <Card key={source}>
                    <SectionTitle
                      icon={<Database size={22} />}
                      title={source}
                      subtitle="Manba holati"
                    />
                    <div className={`status-badge ${status}`}>{status}</div>
                    <p className="muted">
                      Evidence: <b>{count}</b> · Price eligible: <b>{eligible}</b>
                    </p>
                    {message && <p className="muted">{message}</p>}
                  </Card>
                );
              })}
            </div>
          )}

          <Tabs value={activeTab} onChange={setActiveTab} items={tabItems} />

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

                <Card className="full">
                  <SectionTitle
                    icon={<BarChart3 size={22} />}
                    title="Narx tahlili"
                    subtitle="Bitta dona narxi bo‘yicha hisoblangan"
                  />

                  <div className="stats-grid">
                    <StatCard label="Bitimlar soni" value={priceGlobal?.count ?? "—"} />
                    <StatCard label="Minimal narx" value={formatMoney(priceGlobal?.min_price)} />
                    <StatCard label="Maksimal narx" value={formatMoney(priceGlobal?.max_price)} />
                    <StatCard label="O‘rtacha narx" value={formatMoney(priceGlobal?.avg_price)} />
                    <StatCard label="Median narx" value={formatMoney(priceGlobal?.median_price)} />
                    <StatCard
                      label="Tavsiya diapazoni"
                      value={`${formatMoney(priceGlobal?.recommended_min_price)} - ${formatMoney(
                        priceGlobal?.recommended_max_price
                      )}`}
                    />
                  </div>
                </Card>

                {priceBySource && (
                  <Card className="full">
                    <SectionTitle
                      icon={<BarChart3 size={22} />}
                      title="Narx tahlili (manbalar kesimida)"
                      subtitle="Har bir manba bo‘yicha alohida"
                    />

                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Manba</th>
                            <th>Count</th>
                            <th>Median</th>
                            <th>O‘rtacha</th>
                            <th>Izoh</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(priceBySource).map(([source, row]) => (
                            <tr key={source}>
                              <td>{source}</td>
                              <td>{row?.count ?? 0}</td>
                              <td>{formatMoney(row?.median_price)}</td>
                              <td>{formatMoney(row?.avg_price)}</td>
                              <td>{row?.note || row?.excluded_reason || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
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

              {priceGlobal?.suspicious_prices?.length > 0 && (
                <Card className="warning-card">
                  <SectionTitle
                    icon={<ShieldAlert size={22} />}
                    title="Shubhali past narxlar"
                    subtitle="O‘rtacha narxdan 30% yoki undan ko‘proq past bo‘lgan holatlar"
                  />

                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Lot</th>
                          <th>Mahsulot</th>
                          <th>Narx</th>
                          <th>Sabab</th>
                        </tr>
                      </thead>
                      <tbody>
                        {priceGlobal.suspicious_prices.slice(0, 10).map((item, index) => (
                          <tr key={index}>
                            <td>{item.lot_display_no}</td>
                            <td>{item.product_name}</td>
                            <td>{formatMoney(item.unit_price)}</td>
                            <td>{item.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}

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
                  title="Narx trend grafigi"
                  subtitle="Oylar kesimida unit_price dinamikasi"
                />
                <LineChart
                  data={monthlySeries}
                  series={[
                    { key: "median", label: "Median", color: "#2563eb" },
                    { key: "avg", label: "O‘rtacha", color: "#16a34a", opacity: 0.9 },
                    { key: "min", label: "Min", color: "#64748b", opacity: 0.65, width: 2 },
                    { key: "max", label: "Max", color: "#dc2626", opacity: 0.75, width: 2 },
                  ]}
                />
              </Card>

              <Card className="full">
                <SectionTitle
                  icon={<FileText size={22} />}
                  title="Texnik parametrlar summary"
                  subtitle="Evidence tavsiflaridan ajratilgan ko‘p uchragan talablar"
                />
                {(technicalParams.length > 0 || technicalHighlights.length > 0) ? (
                  <div className="chips">
                    {(technicalParams.length > 0 ? technicalParams : technicalHighlights).map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                ) : (
                  <p className="muted">Ma’lumot yo‘q</p>
                )}
              </Card>

              <Card className="full">
                <SectionTitle
                  icon={<BarChart3 size={22} />}
                  title="Hududlar bo‘yicha narx tahlili"
                  subtitle="unit_price bo‘yicha hisoblangan"
                />
                {regionStats.length > 0 ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Hudud</th>
                          <th>Bitimlar soni</th>
                          <th>Median narx</th>
                          <th>O‘rtacha narx</th>
                        </tr>
                      </thead>
                      <tbody>
                        {regionStats.slice(0, 20).map((row) => (
                          <tr key={row.key}>
                            <td>{row.key}</td>
                            <td>{row.count}</td>
                            <td>{formatMoney(row.median)}</td>
                            <td>{formatMoney(row.avg)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">Ma’lumot yo‘q</p>
                )}
              </Card>

              <Card className="full">
                <SectionTitle
                  icon={<BarChart3 size={22} />}
                  title="Supplier / provider tahlili"
                  subtitle="Yetkazib beruvchilar kesimida unit_price"
                />
                {providerStats.length > 0 ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Yetkazib beruvchi</th>
                          <th>Bitimlar soni</th>
                          <th>Median narx</th>
                          <th>O‘rtacha narx</th>
                        </tr>
                      </thead>
                      <tbody>
                        {providerStats.slice(0, 20).map((row) => (
                          <tr key={row.key}>
                            <td>{row.key}</td>
                            <td>{row.count}</td>
                            <td>{formatMoney(row.median)}</td>
                            <td>{formatMoney(row.avg)}</td>
                          </tr>
                        ))}
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
                subtitle="Narx va texnik topshiriq qaysi lotlarga asoslanganini ko‘rsatadi"
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
