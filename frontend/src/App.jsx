import React, { useCallback, useEffect, useMemo, useState } from "react";

const GATEWAY = import.meta.env.VITE_GATEWAY_URL || "http://localhost:8080";
const MONITOR = import.meta.env.VITE_MONITOR_URL || "http://localhost:9000";
const ANOMALY = import.meta.env.VITE_ANOMALY_URL || "http://localhost:9001";

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

const fmt = (n, digits = 1) => n == null ? "—" : Number(n).toFixed(digits);
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
      <Sidebar page={page} setPage={setPage} user={user} onLogout={logout} />
      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">NETWORK OPERATIONS CENTER</div>
            <h1>{page === "dashboard" ? "NetGuardian Dashboard" : page === "services" ? "Service Health" : page === "inventory" ? "Inventory Control" : "Network Topology"}</h1>
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
        {page === "inventory" && <Inventory items={items} onAdjust={adjustStock} />}
        {page === "topology" && <Topology topology={topology} status={status} />}
      </main>
    </div>
  );
}

function Sidebar({ page, setPage, user, onLogout }) {
  const nav = [
    ["dashboard", "▦", "Overview"],
    ["services", "◉", "Services"],
    ["topology", "⌁", "Network Map"],
    ["inventory", "▤", "Inventory"],
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><span>NG</span></div>
        <div><strong>NetGuardian</strong><small>SELF-HEALING NETWORK</small></div>
      </div>
      <div className="side-section">MONITORING</div>
      {nav.map(([id, icon, label]) => (
        <button key={id} className={`nav-item ${page === id ? "active" : ""}`} onClick={() => setPage(id)}>
          <span className="nav-icon">{icon}</span>{label}
        </button>
      ))}
      <div className="side-section">SYSTEM</div>
      <div className="side-status">
        <span className="status-dot green" />
        <div><b>Gateway</b><small>localhost:8080</small></div>
      </div>
      <div className="side-status">
        <span className="status-dot cyan" />
        <div><b>Monitor</b><small>localhost:9000</small></div>
      </div>
      <div className="sidebar-bottom">
        <div className="user-card">
          <div className="avatar small">{(user || "N")[0].toUpperCase()}</div>
          <div><b>{user || "Not signed in"}</b><small>{user ? "Authenticated" : "Login required"}</small></div>
          {user && <button onClick={onLogout} className="logout">↪</button>}
        </div>
        <div className="version">NETGUARDIAN v1.0 • LIVE</div>
      </div>
    </aside>
  );
}

function Dashboard({ status, serviceRows, critical, warning, healthy, upCount, anomalies, lastUpdated, onNavigate }) {
  const avgLatency = serviceRows.length
    ? serviceRows.reduce((sum, s) => sum + Number(s.monitor?.latency || s.latency_ms || 0), 0) / serviceRows.length
    : 0;
  return (
    <div className="content">
      <section className="hero-grid">
        <MetricCard label="NETWORK STATUS" value={status?.overall || "—"} sub={status?.unhealthy?.length ? `${status.unhealthy.length} service(s) affected` : "All monitored services operational"} accent={status?.overall === "HEALTHY" ? "green" : "orange"} icon="◉" />
        <MetricCard label="SERVICES ONLINE" value={`${upCount}/${serviceRows.length || 0}`} sub="Live service health" accent="cyan" icon="◈" />
        <MetricCard label="AVG LATENCY" value={`${fmt(avgLatency)} ms`} sub="Across monitored services" accent="purple" icon="⌁" />
        <MetricCard label="ANOMALIES" value={critical + warning} sub={`${critical} critical · ${warning} warning`} accent={critical ? "red" : warning ? "orange" : "green"} icon="!" />
      </section>

      <div className="section-row">
        <SectionTitle title="SERVICE HEALTH" action="View all" onClick={() => onNavigate("services")} />
        <span className="updated">Updated {lastUpdated ? lastUpdated.toLocaleTimeString() : "—"}</span>
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
        <div><span>Failures</span><b>{m?.failure_rate_pct != null ? `${fmt(m.failure_rate_pct)}%` : "—"}</b></div>
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

export default App;
