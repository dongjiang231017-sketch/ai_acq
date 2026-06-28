import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Bot,
  CheckCircle2,
  ClipboardList,
  Database,
  Headphones,
  MessageSquareText,
  PhoneCall,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Upload,
  Users,
} from "lucide-react";
import { Lead, ModuleSummary, OutreachTask, api } from "./lib/api";

const icons = [BarChart3, Search, Database, PhoneCall, MessageSquareText, Users, Bot, Headphones, ClipboardList, Settings];

const fallbackModules: ModuleSummary[] = [
  { key: "dashboard", name: "实时工作台", description: "监控今日获客、外呼、私信和预警。", pageCount: 4, status: "ready" },
  { key: "collector", name: "线索采集", description: "采集任务、来源配置、清洗规则。", pageCount: 5, status: "ready" },
  { key: "leads", name: "商家线索库", description: "商家资料、电话库、主页和去重审核。", pageCount: 5, status: "ready" },
  { key: "outbound", name: "AI外呼系统", description: "外呼任务、话术流程、通话记录。", pageCount: 6, status: "ready" },
  { key: "dm", name: "平台私信系统", description: "平台账号、私信任务、模板和会话。", pageCount: 6, status: "ready" },
  { key: "intent", name: "意向客户池", description: "客户分级、工单跟进和分配规则。", pageCount: 4, status: "ready" },
  { key: "learning", name: "AI学习中心", description: "建议队列、知识库和实验结果。", pageCount: 5, status: "ready" },
  { key: "voice", name: "声音档案", description: "授权、音色训练和使用记录。", pageCount: 4, status: "ready" },
  { key: "reports", name: "数据报表", description: "渠道、绩效和导出中心。", pageCount: 4, status: "ready" },
  { key: "settings", name: "系统设置", description: "线路、账号、模型 API、权限和审计。", pageCount: 6, status: "ready" },
];

const fallbackLeads: Lead[] = [
  {
    id: "lead_1",
    name: "南山小馆",
    platform: "视频号",
    city: "深圳",
    category: "本地餐饮",
    phone: "13800000001",
    contactName: "陈店长",
    source: "平台采集",
    intentScore: 83,
    status: "待外呼",
  },
  {
    id: "lead_2",
    name: "江南轻食",
    platform: "抖音",
    city: "杭州",
    category: "轻食团购",
    phone: "13800000002",
    contactName: "周经理",
    source: "导入线索",
    intentScore: 71,
    status: "跟进中",
  },
];

const fallbackTasks: OutreachTask[] = [
  { id: "task_1", name: "深圳餐饮商家首轮外呼", channel: "call", status: "运行中", targetCount: 120, scheduledAt: null },
  { id: "task_2", name: "高意向商家私信触达", channel: "dm", status: "待启动", targetCount: 68, scheduledAt: null },
];

function App() {
  const [modules, setModules] = useState<ModuleSummary[]>(fallbackModules);
  const [leads, setLeads] = useState<Lead[]>(fallbackLeads);
  const [tasks, setTasks] = useState<OutreachTask[]>(fallbackTasks);
  const [activeModule, setActiveModule] = useState(fallbackModules[0].key);
  const [apiStatus, setApiStatus] = useState("连接中");
  const [isLoading, setIsLoading] = useState(false);
  const [leadForm, setLeadForm] = useState({
    name: "",
    platform: "视频号",
    city: "",
    category: "",
    phone: "",
    contactName: "",
    source: "手动录入",
  });
  const [taskForm, setTaskForm] = useState({
    name: "",
    channel: "call" as OutreachTask["channel"],
    targetCount: 50,
    scheduledAt: "",
  });

  const active = useMemo(
    () => modules.find((module) => module.key === activeModule) ?? modules[0],
    [activeModule, modules],
  );

  async function loadData() {
    setIsLoading(true);
    try {
      const [health, moduleData, leadData, taskData] = await Promise.all([
        api.health(),
        api.modules(),
        api.leads(),
        api.tasks(),
      ]);
      setApiStatus(health.status === "ok" ? "后端已连接" : health.status);
      setModules(moduleData);
      setLeads(leadData);
      setTasks(taskData);
    } catch {
      setApiStatus("使用前端示例数据");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  async function submitLead(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!leadForm.name.trim() || !leadForm.city.trim() || !leadForm.category.trim()) return;

    const created = await api.createLead({
      ...leadForm,
      phone: leadForm.phone || null,
      contactName: leadForm.contactName || null,
    });
    setLeads((current) => [created, ...current]);
    setLeadForm({ name: "", platform: "视频号", city: "", category: "", phone: "", contactName: "", source: "手动录入" });
  }

  async function submitTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!taskForm.name.trim()) return;

    const created = await api.createTask({
      ...taskForm,
      scheduledAt: taskForm.scheduledAt || null,
      targetCount: Number(taskForm.targetCount),
    });
    setTasks((current) => [created, ...current]);
    setTaskForm({ name: "", channel: "call", targetCount: 50, scheduledAt: "" });
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Sparkles size={20} />
          </span>
          <div>
            <strong>AI获客客户端</strong>
            <small>视频号团购商家</small>
          </div>
        </div>

        <nav className="nav-list" aria-label="功能模块">
          {modules.map((module, index) => {
            const Icon = icons[index] ?? ClipboardList;
            return (
              <button
                className={module.key === activeModule ? "nav-item is-active" : "nav-item"}
                key={module.key}
                onClick={() => setActiveModule(module.key)}
                type="button"
              >
                <Icon size={18} />
                <span>{module.name}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p>{apiStatus}</p>
            <h1>{active?.name ?? "实时工作台"}</h1>
          </div>
          <button className="secondary-button" onClick={loadData} type="button">
            <RefreshCw size={16} className={isLoading ? "spin" : ""} />
            刷新数据
          </button>
        </header>

        <section className="metrics">
          <article>
            <span>模块页面</span>
            <strong>{modules.reduce((sum, module) => sum + module.pageCount, 0)}</strong>
            <small>来自 UI 原型覆盖范围</small>
          </article>
          <article>
            <span>商家线索</span>
            <strong>{leads.length}</strong>
            <small>可接入采集、导入、去重</small>
          </article>
          <article>
            <span>触达任务</span>
            <strong>{tasks.length}</strong>
            <small>外呼、私信、采集任务</small>
          </article>
          <article>
            <span>当前模块</span>
            <strong>{active?.pageCount ?? 0}</strong>
            <small>{active?.description}</small>
          </article>
        </section>

        <section className="content-grid">
          <article className="panel">
            <div className="panel-title">
              <div>
                <p>线索库</p>
                <h2>新增商家线索</h2>
              </div>
              <Upload size={22} />
            </div>
            <form className="form-grid" onSubmit={submitLead}>
              <label>
                商家名称
                <input value={leadForm.name} onChange={(event) => setLeadForm({ ...leadForm, name: event.target.value })} />
              </label>
              <label>
                平台
                <select
                  value={leadForm.platform}
                  onChange={(event) => setLeadForm({ ...leadForm, platform: event.target.value })}
                >
                  <option>视频号</option>
                  <option>抖音</option>
                  <option>小红书</option>
                  <option>美团</option>
                </select>
              </label>
              <label>
                城市
                <input value={leadForm.city} onChange={(event) => setLeadForm({ ...leadForm, city: event.target.value })} />
              </label>
              <label>
                品类
                <input value={leadForm.category} onChange={(event) => setLeadForm({ ...leadForm, category: event.target.value })} />
              </label>
              <label>
                联系人
                <input
                  value={leadForm.contactName}
                  onChange={(event) => setLeadForm({ ...leadForm, contactName: event.target.value })}
                />
              </label>
              <label>
                电话
                <input value={leadForm.phone} onChange={(event) => setLeadForm({ ...leadForm, phone: event.target.value })} />
              </label>
              <button className="primary-button" type="submit">
                <CheckCircle2 size={16} />
                保存线索
              </button>
            </form>
          </article>

          <article className="panel">
            <div className="panel-title">
              <div>
                <p>任务中心</p>
                <h2>创建触达任务</h2>
              </div>
              <PhoneCall size={22} />
            </div>
            <form className="form-grid" onSubmit={submitTask}>
              <label className="wide">
                任务名称
                <input value={taskForm.name} onChange={(event) => setTaskForm({ ...taskForm, name: event.target.value })} />
              </label>
              <label>
                触达方式
                <select
                  value={taskForm.channel}
                  onChange={(event) => setTaskForm({ ...taskForm, channel: event.target.value as OutreachTask["channel"] })}
                >
                  <option value="call">AI外呼</option>
                  <option value="dm">平台私信</option>
                  <option value="collector">线索采集</option>
                </select>
              </label>
              <label>
                目标数量
                <input
                  min={1}
                  type="number"
                  value={taskForm.targetCount}
                  onChange={(event) => setTaskForm({ ...taskForm, targetCount: Number(event.target.value) })}
                />
              </label>
              <label className="wide">
                预约时间
                <input
                  type="datetime-local"
                  value={taskForm.scheduledAt}
                  onChange={(event) => setTaskForm({ ...taskForm, scheduledAt: event.target.value })}
                />
              </label>
              <button className="primary-button" type="submit">
                <CheckCircle2 size={16} />
                创建任务
              </button>
            </form>
          </article>
        </section>

        <section className="content-grid lower">
          <article className="panel">
            <div className="panel-title">
              <div>
                <p>最近线索</p>
                <h2>商家跟进列表</h2>
              </div>
              <Users size={22} />
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>商家</th>
                    <th>城市</th>
                    <th>平台</th>
                    <th>意向</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.length === 0 && (
                    <tr>
                      <td colSpan={5}>
                        <span className="empty-state">暂无线索，先新增一条商家线索。</span>
                      </td>
                    </tr>
                  )}
                  {leads.map((lead) => (
                    <tr key={lead.id}>
                      <td>
                        <strong>{lead.name}</strong>
                        <small>{lead.category}</small>
                      </td>
                      <td>{lead.city}</td>
                      <td>{lead.platform}</td>
                      <td>{lead.intentScore}</td>
                      <td>
                        <span className="badge">{lead.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          <article className="panel">
            <div className="panel-title">
              <div>
                <p>任务队列</p>
                <h2>触达执行状态</h2>
              </div>
              <MessageSquareText size={22} />
            </div>
            <div className="task-list">
              {tasks.length === 0 && <div className="empty-state">暂无任务，先创建一个外呼或私信任务。</div>}
              {tasks.map((task) => (
                <div className="task-row" key={task.id}>
                  <span>{task.channel === "call" ? "外呼" : task.channel === "dm" ? "私信" : "采集"}</span>
                  <div>
                    <strong>{task.name}</strong>
                    <small>{task.targetCount} 个目标</small>
                  </div>
                  <em>{task.status}</em>
                </div>
              ))}
            </div>
          </article>
        </section>
      </section>
    </main>
  );
}

export default App;
