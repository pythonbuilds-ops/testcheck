import React, { useState, useEffect } from 'react';
import { Brain, Database, Clock, Search, Tag, TrendingUp, Trash2, RefreshCw } from 'lucide-react';
import './MemoryDashboard.css';

interface MemoryFact {
  id: number;
  key: string;
  value: string;
  category: string;
  importance: number;
  access_count: number;
  created_at: string;
  last_accessed: string;
  source: string;
}

interface MemoryStats {
  total_facts: number;
  total_episodes: number;
  short_term_items: number;
  by_category: Record<string, number>;
}

interface Episode {
  id: number;
  task_description: string;
  result: string;
  success: number;
  duration_seconds: number;
  created_at: string;
}

interface MemoryDashboardProps {
  wsRef: React.RefObject<WebSocket | null>;
}

const CATEGORY_COLORS: Record<string, string> = {
  user_preference: '#8b5cf6',
  app_knowledge: '#3b82f6',
  device_info: '#10b981',
  learned_procedure: '#f59e0b',
  contact: '#ec4899',
  general: '#6b7280',
};

const CATEGORY_ICONS: Record<string, string> = {
  user_preference: '💜',
  app_knowledge: '📱',
  device_info: '⚙️',
  learned_procedure: '🧠',
  contact: '👤',
  general: '📌',
};

export const MemoryDashboard: React.FC<MemoryDashboardProps> = ({ wsRef }) => {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [memories, setMemories] = useState<MemoryFact[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState<string>('all');

  const requestData = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'get_memory' }));
      wsRef.current.send(JSON.stringify({ type: 'get_memories' }));
      wsRef.current.send(JSON.stringify({ type: 'get_episodes' }));
    }
  };

  useEffect(() => {
    requestData();
    // Listen for responses
    const handler = (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      if (data.type === 'memory_stats') setStats(data.stats);
      if (data.type === 'memories_list') setMemories(data.memories || []);
      if (data.type === 'episodes_list') setEpisodes(data.episodes || []);
    };
    wsRef.current?.addEventListener('message', handler);
    return () => wsRef.current?.removeEventListener('message', handler);
  }, []);

  const deleteMemory = (key: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'delete_memory', key }));
      setMemories(prev => prev.filter(m => m.key !== key));
    }
  };

  const filteredMemories = memories.filter(m => {
    if (filterCategory !== 'all' && m.category !== filterCategory) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return m.key.toLowerCase().includes(q) || m.value.toLowerCase().includes(q);
    }
    return true;
  });

  const maxCatCount = stats ? Math.max(...Object.values(stats.by_category), 1) : 1;

  return (
    <div className="memory-dashboard">
      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(139, 92, 246, 0.15)' }}>
            <Database size={20} style={{ color: '#8b5cf6' }} />
          </div>
          <div className="stat-info">
            <span className="stat-value">{stats?.total_facts ?? '—'}</span>
            <span className="stat-label">Long-term Facts</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(59, 130, 246, 0.15)' }}>
            <Clock size={20} style={{ color: '#3b82f6' }} />
          </div>
          <div className="stat-info">
            <span className="stat-value">{stats?.total_episodes ?? '—'}</span>
            <span className="stat-label">Task Episodes</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: 'rgba(16, 185, 129, 0.15)' }}>
            <Brain size={20} style={{ color: '#10b981' }} />
          </div>
          <div className="stat-info">
            <span className="stat-value">{stats?.short_term_items ?? '—'}</span>
            <span className="stat-label">Short-term Items</span>
          </div>
        </div>
        <button className="stat-card stat-refresh" onClick={requestData}>
          <RefreshCw size={18} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Category Breakdown */}
      <div className="dashboard-card">
        <h3><Tag size={16} /> Category Breakdown</h3>
        <div className="category-bars">
          {stats && Object.entries(stats.by_category).map(([cat, count]) => (
            <div key={cat} className="category-bar-row">
              <span className="cat-label">{CATEGORY_ICONS[cat] || '📌'} {cat.replace('_', ' ')}</span>
              <div className="cat-bar-track">
                <div
                  className="cat-bar-fill"
                  style={{
                    width: `${(count / maxCatCount) * 100}%`,
                    background: CATEGORY_COLORS[cat] || '#6b7280',
                  }}
                />
              </div>
              <span className="cat-count">{count}</span>
            </div>
          ))}
          {stats && Object.keys(stats.by_category).length === 0 && (
            <p className="empty-hint">No memories stored yet</p>
          )}
        </div>
      </div>

      {/* Memory List */}
      <div className="dashboard-card memory-list-card">
        <div className="memory-list-header">
          <h3><Database size={16} /> All Memories</h3>
          <div className="memory-filters">
            <div className="search-box">
              <Search size={14} />
              <input
                type="text"
                placeholder="Search memories..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>
            <select
              value={filterCategory}
              onChange={e => setFilterCategory(e.target.value)}
              className="category-filter"
            >
              <option value="all">All Categories</option>
              {Object.keys(CATEGORY_COLORS).map(c => (
                <option key={c} value={c}>{c.replace('_', ' ')}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="memory-table-wrapper">
          {filteredMemories.length === 0 ? (
            <p className="empty-hint">No memories found</p>
          ) : (
            <table className="memory-table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Value</th>
                  <th>Category</th>
                  <th>Imp.</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filteredMemories.map(m => (
                  <tr key={m.id}>
                    <td className="mem-key">{m.key}</td>
                    <td className="mem-value">{m.value.length > 80 ? m.value.slice(0, 80) + '...' : m.value}</td>
                    <td>
                      <span className="cat-badge" style={{ background: (CATEGORY_COLORS[m.category] || '#6b7280') + '22', color: CATEGORY_COLORS[m.category] || '#6b7280' }}>
                        {m.category.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="mem-importance">
                      <div className="importance-dots">
                        {Array.from({ length: 10 }).map((_, i) => (
                          <div key={i} className={`imp-dot ${i < m.importance ? 'filled' : ''}`} />
                        ))}
                      </div>
                    </td>
                    <td>
                      <button className="delete-btn" onClick={() => deleteMemory(m.key)}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Recent Episodes */}
      <div className="dashboard-card">
        <h3><TrendingUp size={16} /> Recent Task Episodes</h3>
        <div className="episodes-list">
          {episodes.length === 0 ? (
            <p className="empty-hint">No task history yet</p>
          ) : (
            episodes.map(ep => (
              <div key={ep.id} className={`episode-item ${ep.success ? 'success' : 'failed'}`}>
                <div className="episode-status">{ep.success ? '✓' : '✗'}</div>
                <div className="episode-info">
                  <span className="episode-task">{ep.task_description}</span>
                  <span className="episode-meta">
                    {ep.duration_seconds?.toFixed(1)}s · {new Date(ep.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
