import { useState } from "react";
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
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();

    if (!query.trim()) {
      setError("Mahsulot nomini kiriting.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

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
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Backend xatolik qaytardi.");
      }


      setResult(data);
      setStep("Tayyor");
    } catch (err) {
      setError(err.message);
      setStep("");
    } finally {
      clearInterval(timer);
      setLoading(false);
    }
  }

  const price = result?.price_analysis;
  const selected = result?.selected_product;

  return (
    <div className="app">
      <div className="hero">
        <div className="hero-badge">
          <Database size={16} />
          Xarid.uzex.uz + AI Technical Task Generator
        </div>

        <h1>AI yordamida xarid texnik topshirig‘i</h1>
        <p>
          Mahsulot yoki xizmat nomini kiriting. Tizim xarid.uzex.uz portalidan
          o‘xshash yakunlangan bitimlarni topadi, narxni tahlil qiladi va
          Ekonom / Standart / Premium texnik topshiriq draftini yaratadi.
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
          </div>

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
                <StatCard label="Bitimlar soni" value={price?.count ?? "—"} />
                <StatCard label="Minimal narx" value={formatMoney(price?.min_price)} />
                <StatCard label="Maksimal narx" value={formatMoney(price?.max_price)} />
                <StatCard label="O‘rtacha narx" value={formatMoney(price?.avg_price)} />
                <StatCard label="Median narx" value={formatMoney(price?.median_price)} />
                <StatCard
                  label="Tavsiya diapazoni"
                  value={`${formatMoney(price?.recommended_min_price)} - ${formatMoney(
                    price?.recommended_max_price
                  )}`}
                />
              </div>
            </Card>
          </div>

          {price?.suspicious_prices?.length > 0 && (
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
                    {price.suspicious_prices.slice(0, 10).map((item, index) => (
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
    </div>
  );
}