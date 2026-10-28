import {
  LayoutDashboard,
  Activity,
  Network,
  Boxes,
  BrainCircuit,
  ShieldCheck,
  RefreshCw,
  LogOut,
  ArrowUpRight,
  Bell,
  Search,
} from "lucide-react";

import React, { useCallback, useEffect, useMemo, useState } from "react";

const GATEWAY = import.meta.env.VITE_GATEWAY_URL || "http://localhost:8080";
const MONITOR = import.meta.env.VITE_MONITOR_URL || "http://localhost:9000";
const ANOMALY = import.meta.env.VITE_ANOMALY_URL || "http://localhost:9001";
const HEALER = import.meta.env.VITE_HEALER_URL || "http://localhost:9002";

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let body = null;
  try { body = await response.json(); } catch {}
  if (!response.ok) {
    const message = body?.detail || body?.message || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body;
}

const fmt = (n, digits = 1) => n == null ? "-" : Number(n).toFixed(digits);
const statusClass = (s) => String(s || "").toLowerCase().replace(/\s+/g, "-");

function App() {
  const [user, setUser] = useState(() => localStorage.getItem("netguardian_user"));
  const [token, setToken] = useState(() => localStorage.getItem("netguardian_token"));
  const [page, setPage] = useState("dashboard");
  const [status, setStatus] = useState(null);
  const [metrics, setMetrics] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [topology, setTopology] = useState(null);
  const [items, setItems] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    const results = await Promise.allSettled([
      requestJson(`${GATEWAY}/api/status`),
      requestJson(`${GATEWAY}/api/topology`),
      requestJson(`${GATEWAY}/api/items`),
      requestJson(`${MONITOR}/metrics`),
      requestJson(`${ANOMALY}/anomalies`),
    ]);
    const [s, t, i, m, a] = results;
    if (s.status === "fulfilled") setStatus(s.value); else setError("Gateway status is unavailable.");
    if (t.status === "fulfilled") setTopology(t.value);
    if (i.status === "fulfilled") setItems(i.value?.items || []);
    if (m.status === "fulfilled") setMetrics(m.value || []);
    if (a.status === "fulfilled") setAnomalies(a.value || []);
    setLastUpdated(new Date());
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  const serviceRows = useMemo(() => {
    const byName = Object.fromEntries(metrics.map(m => [m.service, m]));
    return (status?.services || []).map(s => ({ ...s, monitor: byName[s.service] }));
  }, [status, metrics]);

  const critical = anomalies.filter(a => a.overall_status === "CRITICAL").length;
  const warning = anomalies.filter(a => a.overall_status === "WARNING").length;
  const healthy = anomalies.filter(a => a.overall_status === "HEALTHY").length;
  const upCount = serviceRows.filter(s => s.state === "UP").length;

  const login = async (username, password) => {
    try {
      const data = await requestJson(`${GATEWAY}/api/login`, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      localStorage.setItem("netguardian_user", data.username);
      localStorage.setItem("netguardian_token", data.token);
      setUser(data.username);
      setToken(data.token);
    } catch (e) {
      throw e;
    }
  };

  const logout = () => {
    localStorage.removeItem("netguardian_user");
    localStorage.removeItem("netguardian_token");
    setUser(null);
    setToken(null);
  };

  const adjustStock = async (sku, delta) => {
    if (!token) return;
    try {
      const data = await requestJson(`${GATEWAY}/api/items/${sku}/stock`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: JSON.stringify({ delta }),
      });
      setItems(prev => prev.map(item => item.sku === sku ? data : item));
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="app-shell">
      <Sidebar page={page} setPage={setPage} user={user} onLogout={logout} status={status} />
      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">NETWORK OPERATIONS CENTER</div>
            <h1>
              {{
                dashboard: "NetGuardian Dashboard",
                services: "Service Health",
                inventory: "Inventory Control",
                topology: "Network Topology",
                anomalies: "AI Anomaly Detection",
                healing: "Self-Healing Center",
              }[page] || "NetGuardian Dashboard"}
            </h1>
          </div>
          <div className="top-actions">
            <div className={`live-pill ${status?.overall === "HEALTHY" ? "ok" : "warn"}`}>
              <span className="pulse" /> {status?.overall || "CONNECTING"}
            </div>
            <button className="icon-btn" onClick={refresh} title="Refresh">↻</button>
            <div className="avatar">{(user || "N")[0].toUpperCase()}</div>
          </div>
        </header>

        {error && <div className="alert-banner">⚠ {error}</div>}

        {!user && <LoginModal onLogin={login} />}

        {page === "dashboard" && (
          <Dashboard
            status={status}
            serviceRows={serviceRows}
            critical={critical}
            warning={warning}
            healthy={healthy}
            upCount={upCount}
            anomalies={anomalies}
            lastUpdated={lastUpdated}
            onNavigate={setPage}
          />
        )}
        {page === "services" && <Services rows={serviceRows} anomalies={anomalies} />}
        {page === "topology" && <Topology topology={topology} status={status} />}
        {page === "anomalies" && <AnomalyDetection anomalies={anomalies} />}
        {page === "healing" && <SelfHealing healerUrl={HEALER} />}
      </main>
    </div>
  );
}

function Sidebar({ page, setPage, user, onLogout, status }) {
  const nav = [
    { id: "dashboard", label: "Overview", icon: LayoutDashboard },
    { id: "services", label: "Services", icon: Activity },
    { id: "topology", label: "Network Map", icon: Network },
    { id: "anomalies", label: "AI Detection", icon: BrainCircuit },
    { id: "healing", label: "Self-Healing", icon: ShieldCheck },
  ];
  return (
    <header className="app-header">
      <div className="brandbar">
        <div className="brand">
          <div className="brand-mark"><span>NG</span></div>
          <div><strong>NetGuardian</strong><small>SELF-HEALING NETWORK</small></div>
        </div>
        <div className="brand-context">
          <span className="brand-context-label">NETWORK OPERATIONS CENTER</span>
          <span className="brand-context-detail">Service monitoring and automated recovery</span>
        </div>
        <div className="brand-version">NETGUARDIAN v1.0</div>
      </div>
      <div className="nav-bar">
        <nav className="nav-list" aria-label="Main navigation">
          {nav.map(({ id, icon: Icon, label }) => (
            <button
              key={id}
              className={`nav-item ${page === id ? "active" : ""}`}
              onClick={() => setPage(id)}
              aria-current={page === id ? "page" : undefined}
            >
              <Icon size={17} strokeWidth={1.8} />
              <span>{label}</span>
              {id === "anomalies" && <span className="nav-badge">AI</span>}
            </button>
          ))}
        </nav>
        <div className={`nav-health ${status?.overall === "HEALTHY" ? "ok" : "warn"}`}>
          <span className="status-dot green" />
          <span>{status?.overall || "CONNECTING"}</span>
        </div>
        <div className="nav-user">
          <div className="avatar small">{(user || "N")[0].toUpperCase()}</div>
          <div className="nav-user-copy"><b>{user || "Not signed in"}</b><small>{user ? "Authenticated" : "Login required"}</small></div>
          {user && <button onClick={onLogout} className="logout" aria-label="Log out" title="Log out"><LogOut size={16} /></button>}
        </div>
      </div>
    </header>
  );
}

function Dashboard({ status, serviceRows, critical, warning, healthy, upCount, anomalies, lastUpdated, onNavigate }) {
  const avgLatency = serviceRows.length
    ? serviceRows.reduce((sum, s) => sum + Number(s.monitor?.latency || s.latency_ms || 0), 0) / serviceRows.length
    : 0;
  return (
    <div className="content">
      <section className="hero-grid">
        <MetricCard label="NETWORK STATUS" value={status?.overall || "-"} sub={status?.unhealthy?.length ? `${status.unhealthy.length} service(s) affected` : "All monitored services operational"} accent={status?.overall === "HEALTHY" ? "green" : "orange"} icon="◉" />
        <MetricCard label="SERVICES ONLINE" value={`${upCount}/${serviceRows.length || 0}`} sub="Live service health" accent="cyan" icon="◈" />
        <MetricCard label="AVG LATENCY" value={`${fmt(avgLatency)} ms`} sub="Across monitored services" accent="purple" icon="⌁" />
        <MetricCard label="ANOMALIES" value={critical + warning} sub={`${critical} critical · ${warning} warning`} accent={critical ? "red" : warning ? "orange" : "green"} icon="!" />
      </section>

      <div className="section-row">
        <SectionTitle title="SERVICE HEALTH" action="View all" onClick={() => onNavigate("services")} />
        <span className="updated">Updated {lastUpdated ? lastUpdated.toLocaleTimeString() : "-"}</span>
      </div>
      <div className="service-grid">
        {serviceRows.map(s => <ServiceCard key={s.service} row={s} />)}
      </div>

      <div className="two-col">
        <section className="panel">
          <SectionTitle title="ANOMALY ENGINE" />
          <div className="anomaly-summary">
            <div className="ring">
              <div><strong>{healthy}</strong><small>healthy</small></div>
            </div>
            <div className="severity-list">
              <Severity label="Critical" count={critical} tone="red" />
              <Severity label="Warning" count={warning} tone="orange" />
              <Severity label="Healthy" count={healthy} tone="green" />
            </div>
          </div>
          <div className="event-list">
            {anomalies.filter(a => a.overall_status !== "HEALTHY").slice(0, 4).map(a => (
              <div className="event" key={a.service}>
                <span className={`event-dot ${a.overall_status === "CRITICAL" ? "red" : "orange"}`} />
                <div><b>{a.service}</b><small>{a.rule_anomalies?.[0]?.message || a.ml?.message || "Unusual network behaviour detected"}</small></div>
                <em>{a.overall_status}</em>
              </div>
            ))}
            {!anomalies.some(a => a.overall_status !== "HEALTHY") && <div className="empty">No active anomalies detected.</div>}
          </div>
        </section>

        <section className="panel">
          <SectionTitle title="LIVE METRICS" />
          <div className="mini-chart">
            <div className="chart-grid">
              {[0,1,2,3,4].map(i => <span key={i} style={{top: `${i*25}%`}} />)}
              {serviceRows.map((s, idx) => {
                const value = Math.min(92, Math.max(12, Number(s.monitor?.latency || s.latency_ms || 10) * 3));
                return <div key={s.service} className="bar-wrap" style={{height: `${value}%`}}><div className="bar" /><small>{s.service.replace("-service","")}</small></div>;
              })}
            </div>
          </div>
          <div className="metric-foot"><span>TCP / HTTP latency</span><b>Rolling window: 60 probes</b></div>
        </section>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, accent, icon }) {
  return <div className={`metric-card ${accent}`}><div className="metric-icon">{icon}</div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-sub">{sub}</div></div>;
}

function SectionTitle({ title, action, onClick }) {
  return <div className="section-title"><h2>{title}</h2>{action && <button onClick={onClick}>{action} →</button>}</div>;
}

function Severity({ label, count, tone }) {
  return <div className="severity"><span className={`severity-dot ${tone}`} /><span>{label}</span><b>{count}</b></div>;
}

function ServiceCard({ row }) {
  const m = row.monitor;
  const isUp = row.state === "UP";
  return (
    <div className="service-card">
      <div className="service-head">
        <div className={`service-symbol ${isUp ? "up" : "down"}`}>{row.service === "gateway" ? "GW" : row.service === "auth" ? "AU" : "IN"}</div>
        <div><b>{row.service}</b><small>{row.url}</small></div>
        <span className={`state ${statusClass(row.state)}`}>{row.state}</span>
      </div>
      <div className="service-metrics">
        <div><span>Latency</span><b>{fmt(m?.latency ?? row.latency_ms)} ms</b></div>
        <div><span>Response</span><b>{fmt(m?.response_time)} ms</b></div>
        <div><span>Failures</span><b>{m?.failure_rate_pct != null ? `${fmt(m.failure_rate_pct)}%` : "-"}</b></div>
      </div>
      <div className="spark"><span /><span /><span /><span /><span /><span /><span /><span /></div>
    </div>
  );
}

function Services({ rows, anomalies }) {
  return <div className="content">
    <div className="page-intro"><div><div className="eyebrow">LIVE TELEMETRY</div><h2>Service Health</h2><p>Gateway health probes and rolling network metrics from the monitoring service.</p></div><span className="live-pill ok"><span className="pulse" /> AUTO REFRESH 3s</span></div>
    <div className="table-panel">
      <table><thead><tr><th>Service</th><th>State</th><th>Latency</th><th>Response</th><th>Failure Rate</th><th>P95 Latency</th><th>Consecutive Failures</th><th>Alert</th></tr></thead>
      <tbody>{rows.map(r => {
        const a = anomalies.find(x => x.service === r.service);
        return <tr key={r.service}><td><b>{r.service}</b></td><td><span className={`state ${statusClass(r.state)}`}>{r.state}</span></td><td>{fmt(r.monitor?.latency ?? r.latency_ms)} ms</td><td>{fmt(r.monitor?.response_time)} ms</td><td>{fmt(r.monitor?.failure_rate_pct)}%</td><td>{fmt(r.monitor?.p95_latency_ms)} ms</td><td>{r.monitor?.consecutive_failures ?? 0}</td><td><span className={`alert-tag ${a?.overall_status === "CRITICAL" ? "critical" : a?.overall_status === "WARNING" ? "warning" : "healthy"}`}>{a?.overall_status || "HEALTHY"}</span></td></tr>;
      })}</tbody></table>
    </div>
  </div>;
}

function Inventory({ items, onAdjust }) {
  return <div className="content">
    <div className="page-intro"><div><div className="eyebrow">PROTECTED SERVICE</div><h2>Inventory Control</h2><p>Catalogue data comes through Gateway → Inventory → PostgreSQL. Stock changes require authentication.</p></div></div>
    <div className="inventory-grid">
      {items.map(item => <div className="product-card" key={item.sku}>
        <div className="product-art">{item.name.split(" ").map(w => w[0]).join("").slice(0,3)}</div>
        <div className="sku">{item.sku}</div><h3>{item.name}</h3><div className="price">₹{Number(item.price_inr).toLocaleString("en-IN")}</div>
        <div className="stock-row"><span>Stock</span><b className={item.stock < 10 ? "low" : ""}>{item.stock}</b></div>
        <div className="stock-actions"><button onClick={() => onAdjust(item.sku, -1)}>−</button><button onClick={() => onAdjust(item.sku, 1)}>+</button></div>
      </div>)}
    </div>
  </div>;
}

function Topology({ topology, status }) {
  const nodes = topology?.nodes || [];
  const edges = topology?.edges || [];
  const positions = { gateway:[50,15], auth:[25,48], inventory:[75,48], postgres:[75,82] };
  return <div className="content">
    <div className="page-intro"><div><div className="eyebrow">SERVICE GRAPH</div><h2>Network Topology</h2><p>Live architecture from <code>/api/topology</code>, with service state from <code>/api/status</code>.</p></div></div>
    <div className="topology-panel">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="topology-svg">
        {edges.map((e,i) => {
          const a=positions[e.from], b=positions[e.to]; return <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} className="edge" />;
        })}
      </svg>
      {nodes.map(n => {
        const [x,y]=positions[n.id] || [50,50];
        const state=status?.services?.find(s=>s.service===n.id)?.state || (n.kind==="database" ? "INTERNAL" : "UP");
        return <div key={n.id} className={`node ${n.kind}`} style={{left:`${x}%`,top:`${y}%`}}><div className="node-core">{n.id === "postgres" ? "DB" : n.id.slice(0,2).toUpperCase()}</div><b>{n.id}</b><span>{state}</span></div>;
      })}
      <div className="network-legend"><span><i className="green" /> healthy</span><span><i className="cyan" /> data path</span><span><i className="purple" /> database</span></div>
    </div>
  </div>;
}

function LoginModal({ onLogin }) {
  const [username,setUsername]=useState("tej"), [password,setPassword]=useState("cn2026"), [busy,setBusy]=useState(false), [error,setError]=useState("");
  const submit=async(e)=>{e.preventDefault();setBusy(true);setError("");try{await onLogin(username,password)}catch(err){setError(err.message)}finally{setBusy(false)}};
  return <div className="login-overlay"><form className="login-card" onSubmit={submit}>
    <div className="brand centered"><div className="brand-mark"><span>NG</span></div><div><strong>NetGuardian</strong><small>SECURE ACCESS</small></div></div>
    <h2>Sign in to NOC</h2><p>Authenticate through the Gateway service to unlock protected controls.</p>
    <label>Username<input value={username} onChange={e=>setUsername(e.target.value)} /></label>
    <label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} /></label>
    {error && <div className="form-error">{error}</div>}
    <button className="primary" disabled={busy}>{busy ? "Authenticating…" : "Sign in →"}</button>
    <small className="demo">Demo users: <b>tej / cn2026</b> · admin / admin123 · guest / guest</small>
  </form></div>;
}


function AnomalyDetection({ anomalies }) {
  const critical = anomalies.filter((a) => a.overall_status === "CRITICAL");
  const warning = anomalies.filter((a) => a.overall_status === "WARNING");
  const healthy = anomalies.filter((a) => a.overall_status === "HEALTHY");

  return (
    <div className="content">
      <div className="page-intro">
        <div>
          <div className="eyebrow">MACHINE LEARNING · SECURITY</div>
          <h2>AI Anomaly Detection</h2>
          <p>
            Monitor service anomalies, rule-based alerts, and AI-generated
            feature sensitivity explanations.
          </p>
        </div>
        <span className="live-pill ok">
          <span className="pulse" /> LIVE DATA
        </span>
      </div>

      <div className="hero-grid anomaly-stats">
        <MetricCard label="CRITICAL" value={critical.length} sub="Services requiring attention" accent="red" icon="!" />
        <MetricCard label="WARNING" value={warning.length} sub="Services to investigate" accent="orange" icon="!" />
        <MetricCard label="HEALTHY" value={healthy.length} sub="Services without active alerts" accent="green" icon="✓" />
        <MetricCard label="MONITORED" value={anomalies.length} sub="Services returned by the anomaly API" accent="cyan" icon="AI" />
      </div>

      {anomalies.length === 0 ? (
        <section className="panel">
          <div className="empty">
            No anomaly records available. Check that the anomaly API is running.
          </div>
        </section>
      ) : (
        <div className="anomaly-cards">
          {anomalies.map((anomaly, index) => {
            const ml = anomaly.ml;
            const explanation = ml?.explanation;
            const features = explanation?.feature_explanations ?? [];
            const rules = anomaly.rule_anomalies ?? [];
            const state = anomaly.overall_status ?? "UNKNOWN";

            return (
              <section className="panel" key={anomaly.service || index} style={{ marginBottom: 18 }}>
                <div className="section-title">
                  <h2>{anomaly.service || "Unknown service"}</h2>
                  <span className={`alert-tag ${statusClass(state)}`}>{state}</span>
                </div>

                <div className="service-metrics">
                  <div><span>Network status</span><b>{anomaly.network_status ?? "Unknown"}</b></div>
                  <div><span>Rule alerts</span><b>{rules.length}</b></div>
                  <div><span>ML decision score</span><b>{ml?.score != null ? fmt(ml.score, 4) : "-"}</b></div>
                </div>

                <div style={{ marginTop: 20 }}>
                  <h3>Rule-based signals</h3>
                  {rules.length ? (
                    <ul>
                      {rules.map((rule, i) => (
                        <li key={`${rule.type}-${i}`}>
                          <strong>{rule.type}</strong> - {rule.message}
                        </li>
                      ))}
                    </ul>
                  ) : <p>No rule-based alerts.</p>}
                </div>

                <div style={{ marginTop: 20 }}>
                  <h3>Machine learning result</h3>
                  <p>{ml?.message ?? "No ML result returned."}</p>
                  {ml?.is_anomaly && <span className="alert-tag warning">ML ANOMALY</span>}
                </div>

                <div style={{ marginTop: 20 }}>
                  <h3>Explainable AI · Feature sensitivity</h3>
                  {explanation?.top_feature ? (
                    <>
                      <p>
                        Most sensitive feature: <strong>{explanation.top_feature}</strong>
                      </p>
                      <p>Explanation method: {explanation.method ?? "Sensitivity analysis"}</p>
                      {features.length > 0 ? (
                        <div className="table-panel">
                          <table>
                            <thead>
                              <tr><th>Feature</th><th>Observed value</th><th>Sensitivity</th></tr>
                            </thead>
                            <tbody>
                              {features.map((feature) => (
                                <tr key={feature.feature}>
                                  <td><strong>{feature.feature}</strong></td>
                                  <td>{fmt(feature.value, 3)}</td>
                                  <td>{fmt(feature.sensitivity, 6)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : <p>No feature-level details returned.</p>}
                    </>
                  ) : (
                    <p>No feature sensitivity explanation is available for this result.</p>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
      <p className="metric-foot anomaly-note">
        Sensitivity measures how the model score changes under tested feature perturbations;
        it is not a probability or proof of causation.
      </p>
    </div>
  );
}

function SelfHealing({ healerUrl }) {
  const [snapshot, setSnapshot] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const [statusData, eventData] = await Promise.all([
        requestJson(`${healerUrl}/healing/status`),
        requestJson(`${healerUrl}/healing/events?limit=50`),
      ]);
      setSnapshot(statusData);
      setEvents(Array.isArray(eventData) ? eventData : eventData.events || []);
      setError("");
    } catch (e) {
      setError(`Self-healing API unavailable: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [healerUrl]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [load]);

  const action = async (path, confirmation) => {
    if (confirmation && !window.confirm(confirmation)) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await requestJson(`${healerUrl}${path}`, {
        method: "POST",
      });
      const messages = {
        "/healing/pause": "Automatic healing paused successfully.",
        "/healing/resume": "Automatic healing resumed successfully.",
      };

      setNotice(messages[path] || result?.message || "Action completed successfully.");
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const services = snapshot?.services || [];
  const overall = snapshot?.overall || "UNKNOWN";
  const paused = snapshot?.paused === true ||
    snapshot?.healer === "PAUSED";

  return (
    <section className="page-content">
      <div className="page-intro">
        <div>
          <div className="eyebrow">AUTOMATED REMEDIATION</div>
          <h2>Self-Healing Center</h2>
          <p>Monitor service recovery, restart attempts, and healing events.</p>
        </div>
        <button className="secondary-btn" onClick={load} disabled={loading}>
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {error && <div className="alert-banner">{error}</div>}
      {notice && <div className="alert-banner">{notice}</div>}

      <div className="stats-grid">
        <div className="stat-card">
          <span>Healer Status</span>
          <strong>{paused ? "PAUSED" : overall}</strong>
        </div>
        <div className="stat-card">
          <span>Monitored Services</span>
          <strong>{services.length}</strong>
        </div>
        <div className="stat-card">
          <span>Total Restarts</span>
          <strong>{snapshot?.total_restarts ?? 0}</strong>
        </div>
        <div className="stat-card">
          <span>Successful Recoveries</span>
          <strong>{snapshot?.total_recoveries ?? 0}</strong>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Recovery Controls</h3>
            <p>Automatic remediation can be paused without stopping monitoring.</p>
          </div>
          <button
            className="primary-btn"
            disabled={busy || loading || !snapshot}
            onClick={() => action(
              paused ? "/healing/resume" : "/healing/pause",
              `Are you sure you want to ${paused ? "resume" : "pause"} automatic healing?`
            )}
          >
            {paused ? "Resume Healing" : "Pause Healing"}
          </button>
        </div>
        <p className="muted">
          Automatic actions restart real Docker containers. Use manual recovery
          only when you intend to affect the selected service.
        </p>
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Service Recovery Status</h3>
            <p>Live state and recovery statistics from the healer backend.</p>
          </div>
        </div>

        {loading && <p>Loading self-healing status…</p>}
        {!loading && !error && services.length === 0 &&
          <p>No service status records returned by the API.</p>}

        {services.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Service</th>
                  <th>State</th>
                  <th>Container</th>
                  <th>Restarts</th>
                  <th>Recoveries</th>
                  <th>Last Recovery</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {services.map((s) => (
                  <tr key={s.service}>
                    <td>{s.service}</td>
                    <td>
                      <span className={`status-badge ${String(s.state || "").toLowerCase()}`}>
                        {s.state || "UNKNOWN"}
                      </span>
                    </td>
                    <td>{s.container || "-"}</td>
                    <td>{s.total_restarts ?? 0}</td>
                    <td>{s.total_recoveries ?? 0}</td>
                    <td>
                      {s.last_recovery_s == null
                        ? "Never"
                        : `${Number(s.last_recovery_s).toFixed(1)} s`}
                    </td>
                    <td>
                      <button
                        className="secondary-btn"
                        disabled={busy || loading}
                        onClick={() => action(
                          `/healing/heal/${encodeURIComponent(s.service)}`,
                          `Trigger a real recovery action for ${s.service}? This may start or restart its Docker container.`
                        )}
                      >
                        Heal
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>Recent Healing Events</h3>
            <p>Latest decisions, remediation attempts, and recovery outcomes.</p>
          </div>
          <span className="muted">{events.length} events</span>
        </div>

        {events.length === 0
          ? <p>No healing events returned yet.</p>
          : (
            <div className="event-list">
              {events.map((event, index) => (
                <div className="event-row" key={`${event.ts}-${index}`}>
                  <div>
                    <strong>{event.event || "EVENT"}</strong>
                    <p>{event.service || "System"} · {event.detail || event.msg || ""}</p>
                  </div>
                  <time>{event.ts ? new Date(event.ts * 1000).toLocaleTimeString() : "Recent"}</time>
                </div>
              ))}
            </div>
          )}
      </div>
    </section>
  );
}


export default App;
