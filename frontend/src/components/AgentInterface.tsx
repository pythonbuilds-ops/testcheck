import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Send, Smartphone, Cpu, MessageSquare, Brain, CalendarClock, Palette, Menu, X, ArrowRight, Zap, ChevronRight } from 'lucide-react';
import { CollapsibleTaskChain } from './CollapsibleTaskChain';
import { MemoryDashboard } from './MemoryDashboard';
import { Scheduler } from './Scheduler';
import { ThemeSettings } from './ThemeSettings';
import { getWebSocketUrl } from '../lib/runtime';
import './AgentInterface.css';

export interface TaskStep {
  id: string;
  type: 'status' | 'tool_call' | 'tool_result';
  message?: string;
  name?: string;
  args?: any;
  result?: any;
}

interface Message {
  id: string;
  sender: 'user' | 'agent';
  type: 'text' | 'task_chain';
  text?: string;
  steps?: TaskStep[];
  isComplete?: boolean;
  timestamp: string;
}

type ViewMode = 'chat' | 'memory' | 'scheduler';

export const AgentInterface: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const [deviceInfo, setDeviceInfo] = useState<any>(null);
  const [memoryStats, setMemoryStats] = useState<any>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('chat');
  const [showTheme, setShowTheme] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [greetingText, setGreetingText] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const seenMsgIds = useRef<Set<string>>(new Set());
  const isInitRef = useRef(true);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // WebSocket connection
  useEffect(() => {
    const ws = new WebSocket(getWebSocketUrl('/ws/web-client'));
    wsRef.current = ws;
    const pollRuntime = () => {
      if (ws.readyState !== WebSocket.OPEN) {
        return;
      }
      ws.send(JSON.stringify({ type: 'get_device' }));
      ws.send(JSON.stringify({ type: 'get_memory' }));
    };
    const pollInterval = window.setInterval(pollRuntime, 15000);

    ws.onopen = () => {
      setConnected(true);
      pollRuntime();
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      // Server-side dedup: if the server sends a msg_id, skip if already seen
      if (data.msg_id) {
        if (seenMsgIds.current.has(data.msg_id)) return;
        seenMsgIds.current.add(data.msg_id);
      }

      if (data.type === 'agent_message') {
        setIsTyping(false);
        setMessages(prev => {
          // Extra dedup guard: skip if last agent text message has identical text
          const lastAgentText = [...prev].reverse().find(m => m.sender === 'agent' && m.type === 'text');
          if (lastAgentText && lastAgentText.text === data.message) return prev;

          const newMessages = [...prev];
          const lastMsg = newMessages[newMessages.length - 1];
          if (lastMsg && lastMsg.sender === 'agent' && lastMsg.type === 'task_chain') {
            lastMsg.isComplete = true;
          }
          newMessages.push({
            id: Date.now().toString() + Math.random(),
            sender: 'agent',
            type: 'text',
            text: data.message,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          });
          return newMessages;
        });
      } else if (data.type === 'status' || data.type === 'tool_call' || data.type === 'tool_result') {
        if (isInitRef.current) return; // Hide all setup steps from chat UI

        setIsTyping(true);
        setMessages(prev => {
          const newMessages = [...prev];
          let lastMsg = newMessages[newMessages.length - 1];

          if (!lastMsg || lastMsg.sender !== 'agent' || lastMsg.type !== 'task_chain' || lastMsg.isComplete) {
            lastMsg = {
              id: Date.now().toString() + Math.random(),
              sender: 'agent',
              type: 'task_chain',
              steps: [],
              isComplete: false,
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            };
            newMessages.push(lastMsg);
          }

          // Skip consecutive identical steps (status, tool_call, or tool_result)
          if (lastMsg.steps && lastMsg.steps.length > 0) {
            const lastStep = lastMsg.steps[lastMsg.steps.length - 1];
            if (lastStep.type === data.type) {
              // Same type — check for identical content
              if (data.type === 'status' && lastStep.message === data.message) return prev;
              if (data.type === 'tool_call' && lastStep.name === data.name && JSON.stringify(lastStep.args) === JSON.stringify(data.args)) return prev;
              if (data.type === 'tool_result' && lastStep.name === data.name && JSON.stringify(lastStep.result) === JSON.stringify(data.result)) return prev;
            }
          }

          lastMsg.steps!.push({
            id: Date.now().toString() + Math.random(),
            type: data.type,
            message: data.message,
            name: data.name,
            args: data.args,
            result: data.result,
          });
          return newMessages;
        });
      } else if (data.type === 'greeting') {
        setGreetingText(data.text || '');
      } else if (data.type === 'device_info') {
        setDeviceInfo(data.info);
        isInitRef.current = false;
        setIsInitializing(false);
        setIsTyping(false); // Clear any stuck typing indicator
      } else if (data.type === 'memory_stats') {
        setMemoryStats(data.stats);
      }
    };

    ws.onclose = () => setConnected(false);
    return () => {
      window.clearInterval(pollInterval);
      ws.close();
    };
  }, []);

  const handleSendMessage = useCallback((e?: React.FormEvent, overrideMsg?: string) => {
    e?.preventDefault();
    const msg = overrideMsg || inputValue.trim();
    if (!msg || !wsRef.current) return;

    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      sender: 'user',
      type: 'text',
      text: msg,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }]);

    wsRef.current.send(JSON.stringify({ type: 'user_message', message: msg }));
    setInputValue('');
    setIsTyping(true);
    setViewMode('chat');
  }, [inputValue]);

  // Returns the agent's response text so the scheduler can log success/failure
  const handleScheduledTask = useCallback((desc: string): Promise<string> => {
    return new Promise((resolve) => {
      const msg = `[Scheduled] ${desc}`;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        resolve('WebSocket not connected');
        return;
      }

      setMessages(prev => [...prev, {
        id: Date.now().toString() + Math.random(),
        sender: 'user',
        type: 'text',
        text: msg,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }]);

      // Listen for the agent_message response
      const handler = (event: MessageEvent) => {
        const data = JSON.parse(event.data);
        if (data.type === 'agent_message') {
          wsRef.current?.removeEventListener('message', handler);
          resolve(data.message || 'Completed');
        }
      };
      wsRef.current.addEventListener('message', handler);
      // Timeout after 2 minutes
      setTimeout(() => {
        wsRef.current?.removeEventListener('message', handler);
        resolve('Timed out waiting for response');
      }, 120000);

      wsRef.current.send(JSON.stringify({ type: 'user_message', message: msg }));
      setIsTyping(true);
      setViewMode('chat');
    });
  }, []);

  const navItems = [
    { id: 'chat' as ViewMode, icon: MessageSquare, label: 'Chat' },
    { id: 'memory' as ViewMode, icon: Brain, label: `Memory ${memoryStats ? `(${memoryStats.total_facts})` : ''}` },
    { id: 'scheduler' as ViewMode, icon: CalendarClock, label: 'Scheduler' },
  ];

  return (
    <div className="agent-interface-container">
      {/* Mobile toggle */}
      <button className="sidebar-toggle glass-panel" onClick={() => setSidebarOpen(!sidebarOpen)}>
        {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* Sidebar */}
      <aside className={`sidebar glass-panel ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <div className="logo-container">
            <div className="logo-icon">
              <Zap size={18} />
            </div>
            <div>
              <h2>PhoneAgent</h2>
              <div className={`connection-badge ${connected ? 'online' : ''}`}>
                <span className="conn-dot" />
                {connected ? 'Connected' : 'Offline'}
              </div>
            </div>
          </div>
        </div>

        {/* Device Card */}
        {deviceInfo && (
          <div className="sidebar-card device-card">
            <div className="card-icon"><Smartphone size={16} /></div>
            <div className="card-content">
              <span className="card-title">{deviceInfo.model || 'Device'}</span>
              <span className="card-meta">Android {deviceInfo.android_version} · 🔋 {deviceInfo.battery_level}</span>
            </div>
          </div>
        )}

        {/* Navigation */}
        <nav className="sidebar-nav">
          {navItems.map(item => (
            <button
              key={item.id}
              className={`nav-item ${viewMode === item.id ? 'active' : ''}`}
              onClick={() => { setViewMode(item.id); setSidebarOpen(false); }}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {viewMode === item.id && <ChevronRight size={14} className="nav-indicator" />}
            </button>
          ))}
        </nav>

        {/* Sidebar Footer */}
        <div className="sidebar-footer">
          <button className="theme-btn" onClick={() => setShowTheme(true)}>
            <Palette size={16} />
            <span>Appearance</span>
          </button>
          <div className="sidebar-stats">
            <span><Cpu size={12} /> {memoryStats?.total_episodes || 0} tasks</span>
            <span><Brain size={12} /> {memoryStats?.total_facts || 0} memories</span>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content glass-panel">
        {viewMode === 'chat' && (
          <>
            <header className="chat-header">
              <div className="header-info">
                <h2>Command Center</h2>
                <p>{connected ? 'Ready for commands' : 'Connecting...'}</p>
              </div>
              <div className="header-badges">
                <div className={`status-badge ${connected ? 'online' : ''}`}>
                  <span className="badge-dot" />
                  {connected ? 'Live' : 'Offline'}
                </div>
              </div>
            </header>
            
            {/* Chat Area */}
        <div className="messages-area">
          {isInitializing ? (
            <div className="init-overlay">
              <div className="init-spinner">
                <div className="init-ring"></div>
                <div className="init-ring"></div>
                <div className="init-ring"></div>
                <Cpu className="init-icon" size={28} />
              </div>
              <h3 className="init-title">Initializing Agent Framework...</h3>
              <p className="init-subtitle">Loading tools and establishing device connection</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="empty-chat">
              {greetingText ? (
                <h2 className="greeting-header">{greetingText}</h2>
              ) : (
                <>
                  <div className="empty-icon"><Zap size={32} /></div>
                  <h3>Ready for commands</h3>
                </>
              )}
              <p>I'm connected and ready to assist you with your device.</p>
              <div className="quick-actions">
                <button className="quick-action-btn" onClick={() => handleSendMessage(undefined, "Check my battery status")}>
                  Check Battery
                </button>
                <button className="quick-action-btn" onClick={() => handleSendMessage(undefined, "What apps are currently running?")}>
                  List Running Apps
                </button>
                <button className="quick-action-btn" onClick={() => handleSendMessage(undefined, "Clear my notifications")}>
                  Clear Notifications
                </button>
              </div>
            </div>
          ) : (
            messages.map(msg => (
              <div key={msg.id} className={`message-wrapper ${msg.sender}`}>
                <div className={`message-bubble ${msg.type === 'task_chain' ? 'task-chain-bubble' : ''}`}>
                  <div className="msg-header">
                    <span className="msg-sender">{msg.sender === 'user' ? 'You' : 'Agent'}</span>
                    <span className="msg-time">{msg.timestamp}</span>
                  </div>
                  {msg.type === 'text' && <div className="msg-body">{msg.text}</div>}
                  {msg.type === 'task_chain' && msg.steps && (
                    <CollapsibleTaskChain steps={msg.steps} isComplete={!!msg.isComplete} />
                  )}
                </div>
              </div>
            ))
          )}
              {isTyping && (
                <div className="message-wrapper agent">
                  <div className="typing-indicator">
                    <span /><span /><span />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <form className="input-area" onSubmit={handleSendMessage}>
              <div className="input-wrapper glass-panel">
                <ArrowRight size={18} className="input-icon" />
                <input
                  type="text"
                  value={inputValue}
                  onChange={e => setInputValue(e.target.value)}
                  placeholder='e.g., "open Settings and turn on WiFi"'
                  className="command-input"
                  disabled={!connected}
                />
                <button type="submit" className="send-btn" disabled={!inputValue.trim() || !connected}>
                  <Send size={16} />
                </button>
              </div>
            </form>
          </>
        )}

        {viewMode === 'memory' && <MemoryDashboard wsRef={wsRef} />}
        {viewMode === 'scheduler' && <Scheduler onFireTask={handleScheduledTask} />}
      </main>

      {/* Theme Modal */}
      {showTheme && <ThemeSettings onClose={() => setShowTheme(false)} />}
    </div>
  );
};
