import React, { useState, useEffect, useRef } from 'react';
import { CalendarClock, Plus, Trash2, Pause, Play, Clock, CheckCircle, XCircle, ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react';
import './Scheduler.css';

interface ExecutionLog {
  timestamp: string;
  status: 'success' | 'failed' | 'running' | 'timeout';
  response?: string;
}

interface ScheduledTask {
  id: string;
  description: string;
  time: string;       // HH:MM
  recurrence: 'once' | 'daily' | 'weekly';
  enabled: boolean;
  lastRun?: string;
  nextRun?: string;
  executionLogs: ExecutionLog[];
  currentStatus?: 'idle' | 'running' | 'success' | 'failed';
}

interface SchedulerProps {
  onFireTask: (description: string) => Promise<string>;
}

const LS_KEY = 'pa-scheduled-tasks';

function loadSchedules(): ScheduledTask[] {
  try {
    const raw = JSON.parse(localStorage.getItem(LS_KEY) || '[]');
    return raw.map((t: any) => ({ ...t, executionLogs: t.executionLogs || [], currentStatus: t.currentStatus || 'idle' }));
  } catch { return []; }
}

function saveSchedules(tasks: ScheduledTask[]) {
  localStorage.setItem(LS_KEY, JSON.stringify(tasks));
}

function getNextRun(time: string, recurrence: string): string {
  const now = new Date();
  const [h, m] = time.split(':').map(Number);
  const next = new Date(now);
  next.setHours(h, m, 0, 0);
  if (next <= now) {
    if (recurrence === 'once') return 'expired';
    next.setDate(next.getDate() + (recurrence === 'weekly' ? 7 : 1));
  }
  return next.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function classifyResponse(response: string): 'success' | 'failed' {
  const failIndicators = ['⚠️', 'error', 'failed', 'could not', 'stuck', 'no device', 'timed out'];
  const lower = response.toLowerCase();
  return failIndicators.some(f => lower.includes(f)) ? 'failed' : 'success';
}

export const Scheduler: React.FC<SchedulerProps> = ({ onFireTask }) => {
  const [tasks, setTasks] = useState<ScheduledTask[]>(loadSchedules);
  const [showForm, setShowForm] = useState(false);
  const [newDesc, setNewDesc] = useState('');
  const [newTime, setNewTime] = useState('08:00');
  const [newRecurrence, setNewRecurrence] = useState<'once' | 'daily' | 'weekly'>('daily');
  const [expandedLogs, setExpandedLogs] = useState<Set<string>>(new Set());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => { saveSchedules(tasks); }, [tasks]);

  // Check every 30s if any task should fire
  useEffect(() => {
    const check = () => {
      const now = new Date();
      const currentTime = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

      setTasks(prev => {
        let changed = false;
        const updated = prev.map(t => {
          if (!t.enabled || t.currentStatus === 'running') return t;
          if (t.time !== currentTime) return t;
          // Don't fire if already fired this minute
          if (t.lastRun) {
            const lastRunDate = new Date(t.lastRun);
            if (lastRunDate.getHours() === now.getHours() && lastRunDate.getMinutes() === now.getMinutes()) return t;
          }

          changed = true;
          // Mark as running
          const runningTask = { ...t, currentStatus: 'running' as const, lastRun: now.toISOString() };

          // Fire and track result
          onFireTask(t.description).then(response => {
            const status = classifyResponse(response);
            setTasks(prevTasks => prevTasks.map(pt => {
              if (pt.id !== t.id) return pt;
              const log: ExecutionLog = {
                timestamp: new Date().toISOString(),
                status,
                response: response.substring(0, 300),
              };
              const newTask = {
                ...pt,
                currentStatus: status as 'success' | 'failed',
                executionLogs: [...pt.executionLogs.slice(-9), log], // Keep last 10 logs
                nextRun: getNextRun(pt.time, pt.recurrence),
              };
              if (pt.recurrence === 'once') newTask.enabled = false;
              return newTask;
            }));
          }).catch(err => {
            setTasks(prevTasks => prevTasks.map(pt => {
              if (pt.id !== t.id) return pt;
              const log: ExecutionLog = {
                timestamp: new Date().toISOString(),
                status: 'failed',
                response: String(err).substring(0, 300),
              };
              return {
                ...pt,
                currentStatus: 'failed' as const,
                executionLogs: [...pt.executionLogs.slice(-9), log],
              };
            }));
          });

          return runningTask;
        });
        return changed ? updated : prev;
      });
    };

    intervalRef.current = setInterval(check, 30000);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [onFireTask]);

  const addTask = () => {
    if (!newDesc.trim()) return;
    const task: ScheduledTask = {
      id: Date.now().toString(),
      description: newDesc,
      time: newTime,
      recurrence: newRecurrence,
      enabled: true,
      nextRun: getNextRun(newTime, newRecurrence),
      executionLogs: [],
      currentStatus: 'idle',
    };
    setTasks(prev => [...prev, task]);
    setNewDesc('');
    setShowForm(false);
  };

  const removeTask = (id: string) => setTasks(prev => prev.filter(t => t.id !== id));
  const toggleTask = (id: string) => setTasks(prev => prev.map(t => t.id === id ? { ...t, enabled: !t.enabled } : t));
  const toggleLogs = (id: string) => {
    setExpandedLogs(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const statusIcon = (status?: string) => {
    switch (status) {
      case 'running': return <div className="status-spinner" />;
      case 'success': return <CheckCircle size={14} className="status-success" />;
      case 'failed': return <XCircle size={14} className="status-failed" />;
      default: return <Clock size={14} className="status-idle" />;
    }
  };

  return (
    <div className="scheduler">
      <div className="scheduler-header">
        <div className="scheduler-title">
          <CalendarClock size={20} />
          <h3>Scheduled Tasks</h3>
        </div>
        <button className="add-task-btn" onClick={() => setShowForm(!showForm)}>
          <Plus size={16} />
          <span>New Task</span>
        </button>
      </div>

      {showForm && (
        <div className="schedule-form glass-panel">
          <input
            type="text"
            placeholder="Task description (e.g., 'Check battery and report')"
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            className="schedule-input"
            onKeyDown={e => e.key === 'Enter' && addTask()}
          />
          <div className="schedule-form-row">
            <div className="time-picker">
              <Clock size={14} />
              <input type="time" value={newTime} onChange={e => setNewTime(e.target.value)} />
            </div>
            <div className="recurrence-pills">
              {(['once', 'daily', 'weekly'] as const).map(r => (
                <button
                  key={r}
                  className={`rec-pill ${newRecurrence === r ? 'active' : ''}`}
                  onClick={() => setNewRecurrence(r)}
                >{r}</button>
              ))}
            </div>
            <button className="schedule-add-btn" onClick={addTask}>Add</button>
          </div>
        </div>
      )}

      <div className="scheduled-list">
        {tasks.length === 0 ? (
          <div className="empty-scheduler">
            <CalendarClock size={40} />
            <p>No scheduled tasks yet</p>
            <span>Create automated tasks that run at specific times</span>
          </div>
        ) : (
          tasks.map(t => (
            <div key={t.id} className={`scheduled-item ${t.enabled ? '' : 'disabled'} ${t.currentStatus === 'failed' ? 'has-error' : ''}`}>
              <div className="scheduled-main-row">
                <div className="scheduled-status-icon">{statusIcon(t.currentStatus)}</div>
                <div className="scheduled-info">
                  <span className="scheduled-desc">{t.description}</span>
                  <div className="scheduled-meta">
                    <span className="scheduled-time">{t.time}</span>
                    <span className="scheduled-recurrence">{t.recurrence}</span>
                    {t.nextRun && t.nextRun !== 'expired' && <span className="scheduled-next">Next: {t.nextRun}</span>}
                    {t.lastRun && <span className="scheduled-last">Last: {new Date(t.lastRun).toLocaleString([], { hour: '2-digit', minute: '2-digit' })}</span>}
                  </div>
                  {/* Quick failure preview */}
                  {t.currentStatus === 'failed' && t.executionLogs.length > 0 && (
                    <div className="failure-preview">
                      <AlertTriangle size={12} />
                      <span>{t.executionLogs[t.executionLogs.length - 1].response?.substring(0, 80)}...</span>
                    </div>
                  )}
                </div>
                <div className="scheduled-actions">
                  {t.executionLogs.length > 0 && (
                    <button onClick={() => toggleLogs(t.id)} className="sched-action-btn" title="View logs">
                      {expandedLogs.has(t.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                  )}
                  <button onClick={() => toggleTask(t.id)} className="sched-action-btn" title={t.enabled ? 'Pause' : 'Resume'}>
                    {t.enabled ? <Pause size={14} /> : <Play size={14} />}
                  </button>
                  <button onClick={() => removeTask(t.id)} className="sched-action-btn delete" title="Delete">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {/* Execution Logs */}
              {expandedLogs.has(t.id) && t.executionLogs.length > 0 && (
                <div className="execution-logs">
                  <h4>Execution History</h4>
                  {[...t.executionLogs].reverse().map((log, i) => (
                    <div key={i} className={`exec-log-entry ${log.status}`}>
                      <div className="log-status-dot" />
                      <div className="log-content">
                        <div className="log-header">
                          <span className={`log-badge ${log.status}`}>{log.status}</span>
                          <span className="log-time">{new Date(log.timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                        {log.response && <p className="log-response">{log.response}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
