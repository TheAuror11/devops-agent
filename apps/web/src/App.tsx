import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AgentSpace,
  ChatMessage,
  Health,
  Investigation,
  JournalRecord,
  McpServer,
  Recommendation,
  Runbook,
  Skill,
  TopologyPayload,
  api,
} from "./api";

type View =
  | "overview"
  | "investigations"
  | "investigation"
  | "topology"
  | "runbooks"
  | "skills"
  | "mcp"
  | "prevention";

export function App() {
  const [view, setView] = useState<View>("overview");
  const [health, setHealth] = useState<Health | null>(null);
  const [spaces, setSpaces] = useState<AgentSpace[]>([]);
  const [spaceId, setSpaceId] = useState<string>("");
  const [invs, setInvs] = useState<Investigation[]>([]);
  const [active, setActive] = useState<Investigation | null>(null);
  const [journal, setJournal] = useState<JournalRecord[]>([]);
  const [error, setError] = useState<string>("");

  async function refresh() {
    try {
      const [h, s, i] = await Promise.all([api.health(), api.spaces(), api.investigations()]);
      setHealth(h);
      setSpaces(s);
      setInvs(i);
      if (!spaceId && s[0]) setSpaceId(s[0].id);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 4000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!active) return;
    let stop = false;
    const tick = async () => {
      try {
        const [inv, j] = await Promise.all([api.investigation(active.id), api.journal(active.id)]);
        if (!stop) {
          setActive(inv);
          setJournal(j);
        }
      } catch {
        /* keep last frame */
      }
    };
    void tick();
    const t = setInterval(() => void tick(), 1500);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [active?.id]);

  const space = spaces.find((s) => s.id === spaceId) || spaces[0];
  const openCount = invs.filter((i) => !["COMPLETED", "FAILED", "CANCELLED"].includes(i.status)).length;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">DA</div>
          <div>
            <h1>DevOps Agent</h1>
            <small>Incident control plane</small>
          </div>
        </div>
        {(
          [
            ["overview", "Overview"],
            ["investigations", "Investigations"],
            ["topology", "Topology"],
            ["runbooks", "Runbooks"],
            ["skills", "Skills"],
            ["mcp", "MCP registry"],
            ["prevention", "Prevention"],
          ] as [View, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            className={`navbtn ${view === id || (view === "investigation" && id === "investigations") ? "active" : ""}`}
            onClick={() => setView(id)}
          >
            {label}
          </button>
        ))}
        <div className="health">
          <div>
            <span className={`dot ${health?.status === "ok" ? "ok" : "warn"}`} />
            {health ? `${health.env} · ${health.store}/${health.queue}` : "connecting…"}
          </div>
          <div style={{ marginTop: 6 }}>{health?.bedrock ? "Bedrock tool-calling" : "Local reasoner"}</div>
        </div>
      </aside>
      <main className="main">
        {error && (
          <div className="card" style={{ marginBottom: 16, color: "#f85149" }}>
            API error: {error}. Start the control plane on :8080.
          </div>
        )}
        {view === "overview" && (
          <Overview
            invs={invs}
            space={space}
            openCount={openCount}
            onOpen={(inv) => {
              setActive(inv);
              setView("investigation");
            }}
          />
        )}
        {view === "investigations" && (
          <Investigations
            invs={invs}
            space={space}
            onOpen={(inv) => {
              setActive(inv);
              setView("investigation");
            }}
            onCreated={(inv) => {
              setActive(inv);
              setView("investigation");
              void refresh();
            }}
          />
        )}
        {view === "investigation" && active && (
          <InvestigationDetail
            inv={active}
            journal={journal}
            onBack={() => setView("investigations")}
          />
        )}
        {view === "topology" && space && <TopologyView spaceId={space.id} />}
        {view === "runbooks" && space && <RunbooksView spaceId={space.id} />}
        {view === "skills" && space && <SkillsView spaceId={space.id} />}
        {view === "mcp" && <McpView />}
        {view === "prevention" && <PreventionView spaceId={space?.id} />}
      </main>
    </div>
  );
}

function Overview({
  invs,
  space,
  openCount,
  onOpen,
}: {
  invs: Investigation[];
  space?: AgentSpace;
  openCount: number;
  onOpen: (i: Investigation) => void;
}) {
  const completed = invs.filter((i) => i.status === "COMPLETED").length;
  return (
    <>
      <h2>Overview</h2>
      <p className="sub">
        Agent Space {space?.name || "—"} · autonomous triage, multi-hypothesis RCA, mitigation (recommend-only),
        prevention.
      </p>
      <div className="grid stats">
        <Stat k="Open investigations" v={openCount} />
        <Stat k="Completed" v={completed} />
        <Stat k="MTTR target" v="~70%" />
        <Stat k="Worker scale" v="100+" />
      </div>
      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <strong>Recent investigations</strong>
        </div>
        <InvTable invs={invs.slice(0, 8)} onOpen={onOpen} />
      </div>
    </>
  );
}

function Stat({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="card stat">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

function InvTable({ invs, onOpen }: { invs: Investigation[]; onOpen: (i: Investigation) => void }) {
  if (!invs.length) return <p className="sub">No investigations yet. Start one from Investigations.</p>;
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Status</th>
          <th>Priority</th>
          <th>Started</th>
        </tr>
      </thead>
      <tbody>
        {invs.map((i) => (
          <tr key={i.id} onClick={() => onOpen(i)}>
            <td>{i.title}</td>
            <td>
              <span className={`badge ${i.status}`}>{i.status}</span>
            </td>
            <td>
              <span className={`badge ${i.priority}`}>{i.priority}</span>
            </td>
            <td className="prose">{new Date(i.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Investigations({
  invs,
  space,
  onOpen,
  onCreated,
}: {
  invs: Investigation[];
  space?: AgentSpace;
  onOpen: (i: Investigation) => void;
  onCreated: (i: Investigation) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="row">
        <div>
          <h2>Investigations</h2>
          <p className="sub">Webhook, chat, or manual start. Journal is the audit trail.</p>
        </div>
        <button className="btn" onClick={() => setOpen(true)} disabled={!space}>
          Start investigation
        </button>
      </div>
      <div className="card">
        <InvTable invs={invs} onOpen={onOpen} />
      </div>
      {open && space && (
        <StartModal
          space={space}
          onClose={() => setOpen(false)}
          onCreated={(inv) => {
            setOpen(false);
            onCreated(inv);
          }}
        />
      )}
    </>
  );
}

function StartModal({
  space,
  onClose,
  onCreated,
}: {
  space: AgentSpace;
  onClose: () => void;
  onCreated: (i: Investigation) => void;
}) {
  const [title, setTitle] = useState("Checkout p95 latency cliff");
  const [description, setDescription] = useState(
    "Customers cannot place orders. checkout-p95-latency and checkout-error-rate in ALARM. Payments latency followed ~5 minutes later.",
  );
  const [starting, setStarting] = useState("Latest alarm");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const inv = await api.startInvestigation({
        agent_space_id: space.id,
        title,
        description,
        priority: "HIGH",
        starting_point: starting,
      });
      onCreated(inv);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Start investigation</h2>
        <p className="sub">Agent Space {space.name}</p>
        <label>Title</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
        <div style={{ height: 10 }} />
        <label>Starting point</label>
        <select value={starting} onChange={(e) => setStarting(e.target.value)}>
          <option>Latest alarm</option>
          <option>High CPU usage</option>
          <option>Error rate spike</option>
          <option>manual</option>
        </select>
        <div style={{ height: 10 }} />
        <label>Details</label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="row" style={{ marginTop: 16 }}>
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn" disabled={busy}>
            {busy ? "Enqueueing…" : "Investigate"}
          </button>
        </div>
      </form>
    </div>
  );
}

function InvestigationDetail({
  inv,
  journal,
  onBack,
}: {
  inv: Investigation;
  journal: JournalRecord[];
  onBack: () => void;
}) {
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("Which logs did you analyze?");
  useEffect(() => {
    void api.chat(inv.id).then(setChat).catch(() => undefined);
  }, [inv.id, inv.status]);
  const send = async () => {
    const msg = await api.sendChat(inv.id, draft);
    setChat((c) => [...c, { id: "u", role: "user", content: draft, created_at: new Date().toISOString() }, msg]);
  };
  return (
    <>
      <button className="btn ghost" onClick={onBack} style={{ marginBottom: 12 }}>
        ← All investigations
      </button>
      <div className="row">
        <div>
          <h2>{inv.title}</h2>
          <p className="sub">
            {inv.id} · exec {inv.execution_id} · {inv.starting_point}
          </p>
        </div>
        <span className={`badge ${inv.status}`}>{inv.status}</span>
      </div>
      <div className="split">
        <div className="card journal">
          <strong>Investigation journal</strong>
          <p className="sub">Immutable timeline — tools, hypotheses, operator steers.</p>
          {journal.map((j) => (
            <div className="jitem" key={j.id}>
              <div className="jrail" />
              <div>
                <div className="title">{j.title}</div>
                <div className="meta">
                  {j.record_type} · {j.actor} · {new Date(j.created_at).toLocaleTimeString()}
                </div>
                {j.body && <pre>{j.body.slice(0, 1200)}</pre>}
              </div>
            </div>
          ))}
        </div>
        <div>
          <div className="card" style={{ marginBottom: 12 }}>
            <strong>Hypotheses</strong>
            {(inv.hypotheses || []).map((h) => (
              <div className="hypo" key={h.id}>
                <div className="row">
                  <span>{h.title}</span>
                  <span className={`badge ${h.status}`}>{h.status}</span>
                </div>
                <div className="prose">
                  {(h.confidence * 100).toFixed(0)}% · {h.statement}
                </div>
              </div>
            ))}
            {!inv.hypotheses?.length && <p className="sub">Generating competing theories…</p>}
          </div>
          <div className="card" style={{ marginBottom: 12 }}>
            <strong>Root cause</strong>
            <p className="prose">{inv.root_cause || inv.summary || "Pending evidence."}</p>
          </div>
          {inv.mitigation && (
            <div className="card" style={{ marginBottom: 12 }}>
              <strong>Mitigation (recommend only)</strong>
              <p className="prose">{inv.mitigation.strategy}</p>
              <ol>
                {inv.mitigation.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
            </div>
          )}
          <div className="card">
            <strong>Steer / ask</strong>
            <div className="chatbox">
              {chat.map((m) => (
                <div key={m.id} className={`bubble ${m.role}`}>
                  {m.content}
                </div>
              ))}
            </div>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} />
            <button className="btn" style={{ marginTop: 8 }} onClick={() => void send()}>
              Send
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function TopologyView({ spaceId }: { spaceId: string }) {
  const [g, setG] = useState<TopologyPayload | null>(null);
  useEffect(() => {
    void api.topology(spaceId).then(setG);
  }, [spaceId]);
  const layout = useMemo(() => layoutGraph(g), [g]);
  if (!g) return <p>Loading topology…</p>;
  return (
    <>
      <h2>Application topology</h2>
      <p className="sub">Learned graph used for blast radius and change correlation.</p>
      <svg className="topo" viewBox="0 0 900 520">
        {layout.edges.map((e, i) => (
          <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke="#30363d" strokeWidth="1.5" />
        ))}
        {layout.nodes.map((n) => (
          <g key={n.id}>
            <rect x={n.x - 70} y={n.y - 18} width="140" height="36" rx="8" fill="#1c2330" stroke="#f5a623" />
            <text x={n.x} y={n.y + 1} textAnchor="middle" fill="#e6edf3" fontSize="11" fontFamily="IBM Plex Sans">
              {n.name}
            </text>
            <text x={n.x} y={n.y + 28} textAnchor="middle" fill="#8b949e" fontSize="9">
              {n.kind}
            </text>
          </g>
        ))}
      </svg>
      <div className="node-card">{g.nodes.length} nodes · {g.edges.length} edges</div>
    </>
  );
}

function layoutGraph(g: TopologyPayload | null) {
  const nodes = g?.nodes || [];
  const cols = Math.max(3, Math.ceil(Math.sqrt(nodes.length)));
  const placed = nodes.map((n, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    return { ...n, x: 120 + col * 220, y: 70 + row * 110 };
  });
  const byId = Object.fromEntries(placed.map((n) => [n.id, n]));
  const edges = (g?.edges || [])
    .map((e) => {
      const a = byId[e.source_id];
      const b = byId[e.target_id];
      if (!a || !b) return null;
      return { x1: a.x, y1: a.y, x2: b.x, y2: b.y };
    })
    .filter(Boolean) as { x1: number; y1: number; x2: number; y2: number }[];
  return { nodes: placed, edges };
}

function RunbooksView({ spaceId }: { spaceId: string }) {
  const [items, setItems] = useState<Runbook[]>([]);
  const [sel, setSel] = useState<Runbook | null>(null);
  useEffect(() => {
    void api.runbooks(spaceId).then((r) => {
      setItems(r);
      setSel(r[0] || null);
    });
  }, [spaceId]);
  return (
    <>
      <h2>Runbooks (RAG corpus)</h2>
      <p className="sub">Indexed with BM25 locally; Titan embeddings + OpenSearch in production.</p>
      <div className="split">
        <div className="card">
          {items.map((r) => (
            <div key={r.id} className="hypo" onClick={() => setSel(r)} style={{ cursor: "pointer" }}>
              <strong>{r.title}</strong>
              <div className="prose">{r.tags.join(" · ")}</div>
            </div>
          ))}
        </div>
        <div className="card">
          <strong>{sel?.title}</strong>
          <pre>{sel?.content}</pre>
        </div>
      </div>
    </>
  );
}

function SkillsView({ spaceId }: { spaceId: string }) {
  const [items, setItems] = useState<Skill[]>([]);
  useEffect(() => {
    void api.skills(spaceId).then(setItems);
  }, [spaceId]);
  return (
    <>
      <h2>Skills</h2>
      <p className="sub">Custom operational knowledge attached to this Agent Space.</p>
      {items.map((s) => (
        <div className="card" key={s.id} style={{ marginBottom: 12 }}>
          <strong>{s.name}</strong>
          <div className="prose">{s.description}</div>
          <pre>{s.body}</pre>
        </div>
      ))}
    </>
  );
}

function McpView() {
  const [items, setItems] = useState<McpServer[]>([]);
  useEffect(() => {
    void api.mcp().then(setItems);
  }, []);
  return (
    <>
      <h2>MCP tool registry</h2>
      <p className="sub">Account-level registration, per-space allowlists, read-only enforcement.</p>
      {items.map((s) => (
        <div className="card" key={s.id} style={{ marginBottom: 12 }}>
          <div className="row">
            <strong>{s.name}</strong>
            <span className={`badge ${s.read_only ? "COMPLETED" : "HIGH"}`}>
              {s.read_only ? "read-only" : "writeable"}
            </span>
          </div>
          <div className="prose">{s.endpoint}</div>
          <div className="prose">Allowlist: {s.allowed_tools.join(", ") || "(all listed tools)"}</div>
        </div>
      ))}
    </>
  );
}

function PreventionView({ spaceId }: { spaceId?: string }) {
  const [items, setItems] = useState<Recommendation[]>([]);
  useEffect(() => {
    void api.recommendations(spaceId).then(setItems);
  }, [spaceId]);
  return (
    <>
      <h2>Prevention</h2>
      <p className="sub">Clustered improvements from completed investigations.</p>
      {items.map((r) => (
        <div className="card" key={r.id} style={{ marginBottom: 12 }}>
          <div className="row">
            <strong>{r.title}</strong>
            <span className="badge MEDIUM">{r.category}</span>
          </div>
          <p className="prose">{r.rationale}</p>
          <div className="prose">
            effort {r.effort} · impact {r.impact} · {r.status}
          </div>
        </div>
      ))}
      {!items.length && <p className="sub">Complete an investigation to generate recommendations.</p>}
    </>
  );
}
