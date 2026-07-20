"use client";
import React, { useCallback, useEffect, useState, useRef } from "react";
import dynamic from 'next/dynamic';
import { toast } from 'react-toastify';
import styles from '../../styles/ContractPage.module.css';
import { useRouter } from 'next/navigation';
import { useTheme } from '../../components/ThemeProvider';
import { loadFile, loadSession, loadHistory, sendQuery, uploadFile, deleteSession, sendQueryStream, renameSession, pinSession, unpinSession, attachFileToSession, detachFileFromSession, deleteFile, createSession, getRagModels } from '../../services/ragService';
import * as contractService from '../../services/contractService';
import BotMessage from '../../components/BotMessage';
import ChatInput from '../../components/ChatInput';
import { logout as logoutApi, getMe, getAccounts, updateProfile, uploadAvatar, getAvatarUrl, heartbeatCheck, getNotifications, markNotificationRead, deleteNotification, deleteAllReadNotifications, getLoginHistory, deleteLoginHistoryEntry, deleteLoginHistory, updateRoles, activateAccount, deactivateAccount, deleteAccount, getRoles, createRole, updateRole, deleteRole, getAdminAnalytics, getUserAnalytics, getSystemMetrics } from '../../services/authService';
const FileManagerModal = dynamic(() => import('../../components/FileManagerModal'), { ssr: false });
const ContractManagerModal = dynamic(() => import('../../components/ContractManagerModal'), { ssr: false });
const ReasoningBox = dynamic(() => import('../../components/ReasoningBox'), { ssr: false });
const NotificationListener = dynamic(() => import('../../components/NotificationListener'), { ssr: false });
const UploadProgress = dynamic(() => import('../../components/UploadProgress'), { ssr: false });


// Đã loại bỏ WebSocket

/* Helper formatting for metrics */
const formatBytes = (bytes) => {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

const formatNumber = (num) => {
  if (!num) return '0';
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
  return Math.round(num);
};


/**
 * --- MAIL SERVER MANAGEMENT COMPONENT ---
 */
function MailServerManagement({ styles }) {
    const [configs, setConfigs] = useState([]);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingConfig, setEditingConfig] = useState(null);
    const [formData, setFormData] = useState({
        host: '', port: 587, user: '', password: '', from_email: '', from_name: '', logo_url: '', is_active: false
    });

    const rawApiBase = process.env.NEXT_PUBLIC_API_URL || '';
    const API_BASE = rawApiBase.replace(/\/$/, '');
    const buildAdminUrl = (path) => (API_BASE ? `${API_BASE}${path}` : path);

    const requestMailApi = async (path, options = {}) => {
        const res = await fetch(buildAdminUrl(path), {
            credentials: 'include',
            ...options,
            headers: {
                'Accept': 'application/json',
                ...(options.headers || {}),
            },
        });

        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw {
                status: res.status,
                message: payload?.detail || payload?.message || `HTTP ${res.status}`,
            };
        }
        return payload;
    };

    const getMailConfigs = async () => requestMailApi('/api/v1/admin/settings/mail');
    const addMailConfig = async (data) => requestMailApi('/api/v1/admin/settings/mail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    const updateMailConfig = async (id, data) => requestMailApi(`/api/v1/admin/settings/mail/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    const deleteMailConfig = async (id) => requestMailApi(`/api/v1/admin/settings/mail/${id}`, {
        method: 'DELETE',
    });

    const fetchConfigs = async (isInitial = false) => {
        try {
            const data = await getMailConfigs();
            setConfigs(Array.isArray(data) ? data : []);
        } catch (e) {
            // Im lặng nếu là lần load đầu và backend chưa restart (404)
            if (isInitial && e.status === 404) return;
            console.error("Mail fetch error:", e);
            toast.error("Lỗi khi tải cấu hình mail");
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchConfigs(true);
        }, 0);
        return () => clearTimeout(timer);
    }, []);

    const handleOpenModal = (config = null) => {
        if (config) {
            setEditingConfig(config);
            setFormData({ ...config });
        } else {
            setEditingConfig(null);
            setFormData({ host: '', port: 587, user: '', password: '', from_email: '', from_name: '', logo_url: '', is_active: false });
        }
        setIsModalOpen(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editingConfig) {
                await updateMailConfig(editingConfig.id, formData);
                toast.success("Đã cập nhật cấu hình");
            } else {
                await addMailConfig(formData);
                toast.success("Đã thêm cấu hình mới");
            }
            setIsModalOpen(false);
            fetchConfigs();
        } catch (err) {
            toast.error("Lỗi: " + (err?.message || "Không xác định"));
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm("Bạn có chắc muốn xóa cấu hình này?")) return;
        try {
            await deleteMailConfig(id);
            toast.success("Đã xóa");
            fetchConfigs();
        } catch (e) {
            toast.error("Lỗi khi xóa");
        }
    };

    const handleToggleActive = async (config) => {
        try {
            await updateMailConfig(config.id, { is_active: !config.is_active });
            toast.success("Đã cập nhật trạng thái");
            fetchConfigs();
        } catch (e) {
            toast.error("Lỗi khi cập nhật");
        }
    };

    return (
        <div style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h3 style={{ margin: 0 }}>Cấu hình Mail Server</h3>
                <button 
                    onClick={() => handleOpenModal()}
                    style={{ padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
                >
                    + Thêm mới
                </button>
            </div>

            <div className={styles.tableWrapper}>
                <table className={styles.adminTable}>
                    <thead>
                        <tr>
                            <th>Host</th>
                            <th>User</th>
                            <th>From Email</th>
                            <th>Trạng thái</th>
                            <th>Hành động</th>
                        </tr>
                    </thead>
                    <tbody>
                        {configs.length === 0 ? (
                            <tr><td colSpan="5" style={{ textAlign: 'center', padding: '20px' }}>Chưa có cấu hình nào</td></tr>
                        ) : configs.map(c => (
                            <tr key={c.id}>
                                <td>{c.host}:{c.port}</td>
                                <td>{c.user}</td>
                                <td>{c.from_name} &lt;{c.from_email}&gt;</td>
                                <td>
                                    <span 
                                        onClick={() => handleToggleActive(c)}
                                        style={{ 
                                            padding: '4px 8px', borderRadius: '4px', cursor: 'pointer',
                                            background: c.is_active ? '#10b981' : '#94a3b8', color: 'white', fontSize: '0.8rem'
                                        }}
                                    >
                                        {c.is_active ? "Đang dùng" : "Tạm dừng"}
                                    </span>
                                </td>
                                <td>
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <button onClick={() => handleOpenModal(c)} className={styles.actionBtnSmall}>Sửa</button>
                                        <button onClick={() => handleDelete(c.id)} className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}>Xóa</button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {isModalOpen && (
                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <div style={{ background: 'var(--bg-main)', padding: '24px', borderRadius: '16px', width: '100%', maxWidth: '500px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
                        <h4 style={{ margin: '0 0 20px 0' }}>{editingConfig ? "Sửa cấu hình" : "Thêm cấu hình Mail"}</h4>
                        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div style={{ display: 'flex', gap: '12px' }}>
                                <div style={{ flex: 3 }}>
                                    <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>SMTP Host</label>
                                    <input type="text" value={formData.host} onChange={e => setFormData({...formData, host: e.target.value})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
                                </div>
                                <div style={{ flex: 1 }}>
                                    <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Port</label>
                                    <input type="number" value={formData.port} onChange={e => setFormData({...formData, port: parseInt(e.target.value)})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
                                </div>
                            </div>
                            <div>
                                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>SMTP User</label>
                                <input type="text" value={formData.user} onChange={e => setFormData({...formData, user: e.target.value})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>SMTP Password</label>
                                <input type="password" value={formData.password} onChange={e => setFormData({...formData, password: e.target.value})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required={!editingConfig} />
                            </div>
                            <div style={{ display: 'flex', gap: '12px' }}>
                                <div style={{ flex: 1 }}>
                                    <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Tên hiển thị (From Name)</label>
                                    <input type="text" value={formData.from_name} onChange={e => setFormData({...formData, from_name: e.target.value})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
                                </div>
                                <div style={{ flex: 1 }}>
                                    <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Email gửi (From Email)</label>
                                    <input type="email" value={formData.from_email} onChange={e => setFormData({...formData, from_email: e.target.value})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
                                </div>
                            </div>
                            <div>
                                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Logo URL (Link ảnh cho Email)</label>
                                <input type="text" value={formData.logo_url} onChange={e => setFormData({...formData, logo_url: e.target.value})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} placeholder="https://..." />
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <input type="checkbox" checked={formData.is_active} onChange={e => setFormData({...formData, is_active: e.target.checked})} id="is_active_mail" />
                                <label htmlFor="is_active_mail" style={{ fontSize: '0.9rem' }}>Kích hoạt ngay</label>
                            </div>
                            <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                                <button type="submit" style={{ flex: 1, padding: '10px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Lưu</button>
                                <button type="button" onClick={() => setIsModalOpen(false)} style={{ flex: 1, padding: '10px', background: '#f1f5f9', color: '#475569', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Hủy</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

/**
 * --- TELEGRAM MANAGEMENT COMPONENT ---
 */
function TelegramManagement({ styles }) {
  const [bots, setBots] = useState([]);
  const [recipients, setRecipients] = useState([]);

  const [isBotModalOpen, setIsBotModalOpen] = useState(false);
  const [editingBot, setEditingBot] = useState(null);
  const [botFormData, setBotFormData] = useState({
    bot_id: '',
    bot_token: '',
    is_active: false,
  });

  const [isRecipientModalOpen, setIsRecipientModalOpen] = useState(false);
  const [editingRecipient, setEditingRecipient] = useState(null);
  const [recipientFormData, setRecipientFormData] = useState({
    name: '',
    chat_id: '',
    is_active: true,
  });

  const rawApiBase = process.env.NEXT_PUBLIC_API_URL || '';
  const API_BASE = rawApiBase.replace(/\/$/, '');
  const buildAdminUrl = (path) => (API_BASE ? `${API_BASE}${path}` : path);

  const requestAdminApi = async (path, options = {}) => {
    const res = await fetch(buildAdminUrl(path), {
      credentials: 'include',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.headers || {}),
      },
    });

    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw {
        status: res.status,
        message: payload?.detail || payload?.message || `HTTP ${res.status}`,
      };
    }
    return payload;
  };

  const fetchData = async (isInitial = false) => {
    try {
      const [botData, recipientData] = await Promise.all([
        requestAdminApi('/api/v1/admin/settings/telegram/bots'),
        requestAdminApi('/api/v1/admin/settings/telegram/recipients'),
      ]);
      setBots(Array.isArray(botData) ? botData : []);
      setRecipients(Array.isArray(recipientData) ? recipientData : []);
    } catch (e) {
      if (isInitial && e.status === 404) return;
      toast.error('Lỗi khi tải cấu hình Telegram');
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchData(true);
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const handleOpenBotModal = (bot = null) => {
    if (bot) {
      setEditingBot(bot);
      setBotFormData({ ...bot, bot_token: '' });
    } else {
      setEditingBot(null);
      setBotFormData({ bot_id: '', bot_token: '', is_active: false });
    }
    setIsBotModalOpen(true);
  };

  const handleSubmitBot = async (e) => {
    e.preventDefault();
    try {
      if (editingBot) {
        const payload = { ...botFormData };
        if (!payload.bot_token?.trim()) {
          delete payload.bot_token;
        }
        await requestAdminApi(`/api/v1/admin/settings/telegram/bots/${editingBot.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        toast.success('Đã cập nhật bot Telegram');
      } else {
        await requestAdminApi('/api/v1/admin/settings/telegram/bots', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(botFormData),
        });
        toast.success('Đã thêm bot Telegram');
      }
      setIsBotModalOpen(false);
      fetchData();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleDeleteBot = async (id) => {
    if (!window.confirm('Bạn có chắc muốn xóa bot này?')) return;
    try {
      await requestAdminApi(`/api/v1/admin/settings/telegram/bots/${id}`, {
        method: 'DELETE',
      });
      toast.success('Đã xóa bot Telegram');
      fetchData();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleToggleBotActive = async (bot) => {
    try {
      await requestAdminApi(`/api/v1/admin/settings/telegram/bots/${bot.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !bot.is_active }),
      });
      toast.success('Đã cập nhật trạng thái bot');
      fetchData();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleOpenRecipientModal = (recipient = null) => {
    if (recipient) {
      setEditingRecipient(recipient);
      setRecipientFormData({ ...recipient });
    } else {
      setEditingRecipient(null);
      setRecipientFormData({ name: '', chat_id: '', is_active: true });
    }
    setIsRecipientModalOpen(true);
  };

  const handleSubmitRecipient = async (e) => {
    e.preventDefault();
    try {
      if (editingRecipient) {
        await requestAdminApi(`/api/v1/admin/settings/telegram/recipients/${editingRecipient.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(recipientFormData),
        });
        toast.success('Đã cập nhật người nhận');
      } else {
        await requestAdminApi('/api/v1/admin/settings/telegram/recipients', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(recipientFormData),
        });
        toast.success('Đã thêm người nhận');
      }
      setIsRecipientModalOpen(false);
      fetchData();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleDeleteRecipient = async (id) => {
    if (!window.confirm('Bạn có chắc muốn xóa người nhận này?')) return;
    try {
      await requestAdminApi(`/api/v1/admin/settings/telegram/recipients/${id}`, {
        method: 'DELETE',
      });
      toast.success('Đã xóa người nhận');
      fetchData();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleToggleRecipientActive = async (recipient) => {
    try {
      await requestAdminApi(`/api/v1/admin/settings/telegram/recipients/${recipient.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !recipient.is_active }),
      });
      toast.success('Đã cập nhật trạng thái người nhận');
      fetchData();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  return (
    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ margin: 0 }}>Telegram Bot</h3>
          <button
            onClick={() => handleOpenBotModal()}
            style={{ padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
          >
            + Thêm bot
          </button>
        </div>

        <div className={styles.tableWrapper}>
          <table className={styles.adminTable}>
            <thead>
              <tr>
                <th>Bot ID</th>
                <th>Token</th>
                <th>Trạng thái</th>
                <th>Hành động</th>
              </tr>
            </thead>
            <tbody>
              {bots.length === 0 ? (
                <tr><td colSpan="4" style={{ textAlign: 'center', padding: '20px' }}>Chưa có bot nào</td></tr>
              ) : bots.map((bot) => (
                <tr key={bot.id}>
                  <td>{bot.bot_id}</td>
                  <td>{String(bot.bot_token || '').slice(0, 18)}...</td>
                  <td>
                    <span
                      onClick={() => handleToggleBotActive(bot)}
                      style={{
                        padding: '4px 8px', borderRadius: '4px', cursor: 'pointer',
                        background: bot.is_active ? '#10b981' : '#94a3b8', color: 'white', fontSize: '0.8rem'
                      }}
                    >
                      {bot.is_active ? 'Đang dùng' : 'Tạm dừng'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button onClick={() => handleOpenBotModal(bot)} className={styles.actionBtnSmall}>Sửa</button>
                      <button onClick={() => handleDeleteBot(bot.id)} className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}>Xóa</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ margin: 0 }}>Telegram Recipients</h3>
          <button
            onClick={() => handleOpenRecipientModal()}
            style={{ padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
          >
            + Thêm người nhận
          </button>
        </div>

        <div className={styles.tableWrapper}>
          <table className={styles.adminTable}>
            <thead>
              <tr>
                <th>Tên</th>
                <th>Chat ID</th>
                <th>Trạng thái</th>
                <th>Hành động</th>
              </tr>
            </thead>
            <tbody>
              {recipients.length === 0 ? (
                <tr><td colSpan="4" style={{ textAlign: 'center', padding: '20px' }}>Chưa có người nhận nào</td></tr>
              ) : recipients.map((recipient) => (
                <tr key={recipient.id}>
                  <td>{recipient.name}</td>
                  <td>{recipient.chat_id}</td>
                  <td>
                    <span
                      onClick={() => handleToggleRecipientActive(recipient)}
                      style={{
                        padding: '4px 8px', borderRadius: '4px', cursor: 'pointer',
                        background: recipient.is_active ? '#10b981' : '#94a3b8', color: 'white', fontSize: '0.8rem'
                      }}
                    >
                      {recipient.is_active ? 'Đang dùng' : 'Tạm dừng'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button onClick={() => handleOpenRecipientModal(recipient)} className={styles.actionBtnSmall}>Sửa</button>
                      <button onClick={() => handleDeleteRecipient(recipient.id)} className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}>Xóa</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {isBotModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--bg-main)', padding: '24px', borderRadius: '16px', width: '100%', maxWidth: '560px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
            <h4 style={{ margin: '0 0 20px 0' }}>{editingBot ? 'Sửa bot Telegram' : 'Thêm bot Telegram'}</h4>
            <form onSubmit={handleSubmitBot} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Bot ID</label>
                <input type="text" value={botFormData.bot_id} onChange={(e) => setBotFormData({ ...botFormData, bot_id: e.target.value })} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
              </div>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Bot Token</label>
                <input type="text" value={botFormData.bot_token} onChange={(e) => setBotFormData({ ...botFormData, bot_token: e.target.value })} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required={!editingBot} placeholder={editingBot ? 'Để trống nếu không đổi token' : ''} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input type="checkbox" checked={botFormData.is_active} onChange={(e) => setBotFormData({ ...botFormData, is_active: e.target.checked })} id="is_active_tele_bot" />
                <label htmlFor="is_active_tele_bot" style={{ fontSize: '0.9rem' }}>Kích hoạt bot này</label>
              </div>
              <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                <button type="submit" style={{ flex: 1, padding: '10px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Lưu</button>
                <button type="button" onClick={() => setIsBotModalOpen(false)} style={{ flex: 1, padding: '10px', background: '#f1f5f9', color: '#475569', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Hủy</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isRecipientModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--bg-main)', padding: '24px', borderRadius: '16px', width: '100%', maxWidth: '520px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
            <h4 style={{ margin: '0 0 20px 0' }}>{editingRecipient ? 'Sửa người nhận Telegram' : 'Thêm người nhận Telegram'}</h4>
            <form onSubmit={handleSubmitRecipient} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Tên người nhận</label>
                <input type="text" value={recipientFormData.name} onChange={(e) => setRecipientFormData({ ...recipientFormData, name: e.target.value })} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
              </div>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Chat ID</label>
                <input type="text" value={recipientFormData.chat_id} onChange={(e) => setRecipientFormData({ ...recipientFormData, chat_id: e.target.value })} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} required />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input type="checkbox" checked={recipientFormData.is_active} onChange={(e) => setRecipientFormData({ ...recipientFormData, is_active: e.target.checked })} id="is_active_tele_recipient" />
                <label htmlFor="is_active_tele_recipient" style={{ fontSize: '0.9rem' }}>Kích hoạt người nhận này</label>
              </div>
              <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                <button type="submit" style={{ flex: 1, padding: '10px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Lưu</button>
                <button type="button" onClick={() => setIsRecipientModalOpen(false)} style={{ flex: 1, padding: '10px', background: '#f1f5f9', color: '#475569', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Hủy</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * --- PROMPT MANAGEMENT COMPONENT ---
 */
function PromptManagement({ styles }) {
  const [prompts, setPrompts] = useState([]);
  const [promptFeatures, setPromptFeatures] = useState([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    feature_key: 'custom',
    content: '',
    description: '',
    is_active: true,
  });

  const rawApiBase = process.env.NEXT_PUBLIC_API_URL || '';
  const API_BASE = rawApiBase.replace(/\/$/, '');
  const buildAdminUrl = (path) => (API_BASE ? `${API_BASE}${path}` : path);

  const fallbackFeatures = [
    { feature_key: 'rag_assistant', label: 'RAG Assistant', description: 'Prompt trả lời truy vấn RAG.' },
    { feature_key: 'contract_template_drafter', label: 'Contract Templated', description: 'Prompt tạo hợp đồng theo template.' },
    { feature_key: 'contract_fast_drafter', label: 'Contract Fast', description: 'Prompt tạo hợp đồng nhanh.' },
    { feature_key: 'contract_summary', label: 'Contract Summary', description: 'Prompt tóm tắt hợp đồng.' },
    { feature_key: 'contract_reasoning_drafter', label: 'Reasoning Drafter', description: 'Prompt cho tác tử soạn thảo.' },
    { feature_key: 'contract_reasoning_critic', label: 'Reasoning Critic', description: 'Prompt cho tác tử phản biện.' },
    { feature_key: 'contract_reasoning_reviser', label: 'Reasoning Reviser', description: 'Prompt cho tác tử chỉnh sửa.' },
    { feature_key: 'custom', label: 'Custom', description: 'Prompt mở rộng tự định nghĩa.' },
  ];

  const requestAdminApi = async (path, options = {}) => {
    const res = await fetch(buildAdminUrl(path), {
      credentials: 'include',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.headers || {}),
      },
    });

    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw {
        status: res.status,
        message: payload?.detail || payload?.message || `HTTP ${res.status}`,
      };
    }
    return payload;
  };

  const getFeatureLabel = (featureKey) => {
    const item = promptFeatures.find((f) => f.feature_key === featureKey)
      || fallbackFeatures.find((f) => f.feature_key === featureKey);
    if (!item) return featureKey || 'custom';
    return `${item.label} (${item.feature_key})`;
  };

  const fetchPromptFeatures = async (isInitial = false) => {
    try {
      const data = await requestAdminApi('/api/v1/admin/settings/prompt-features');
      const features = Array.isArray(data?.result) ? data.result : [];
      setPromptFeatures(features.length ? features : fallbackFeatures);
    } catch (e) {
      if (!isInitial) {
        toast.error('Không tải được danh mục chức năng prompt, đang dùng danh sách mặc định.');
      }
      setPromptFeatures(fallbackFeatures);
    }
  };

  const fetchPrompts = async (isInitial = false) => {
    try {
      const data = await requestAdminApi('/api/v1/admin/settings/prompts');
      setPrompts(Array.isArray(data) ? data : []);
    } catch (e) {
      if (isInitial && e.status === 404) return;
      console.error('Prompts fetch error:', e);
      toast.error('Lỗi khi tải prompts');
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchPromptFeatures(true);
      fetchPrompts(true);
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const handleOpenModal = (p = null) => {
    if (p) {
      setEditingPrompt(p);
      setFormData({
        name: p.name || '',
        feature_key: p.feature_key || 'custom',
        content: p.content || '',
        description: p.description || '',
        is_active: !!p.is_active,
      });
    } else {
      setEditingPrompt(null);
      setFormData({
        name: '',
        feature_key: 'custom',
        content: '',
        description: '',
        is_active: true,
      });
    }
    setIsModalOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = {
      ...formData,
      feature_key: formData.feature_key || 'custom',
    };

    try {
      if (editingPrompt) {
        await requestAdminApi(`/api/v1/admin/settings/prompts/${editingPrompt.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        toast.success('Đã cập nhật prompt');
      } else {
        await requestAdminApi('/api/v1/admin/settings/prompts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        toast.success('Đã thêm prompt mới');
      }
      setIsModalOpen(false);
      fetchPrompts();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Bạn có chắc muốn xóa prompt này?')) return;
    try {
      await requestAdminApi(`/api/v1/admin/settings/prompts/${id}`, { method: 'DELETE' });
      toast.success('Đã xóa prompt');
      fetchPrompts();
    } catch (e) {
      toast.error(`Lỗi khi xóa: ${e?.message || 'Không xác định'}`);
    }
  };

  const handleToggleActive = async (p) => {
    try {
      await requestAdminApi(`/api/v1/admin/settings/prompts/${p.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !p.is_active }),
      });
      toast.success('Đã cập nhật trạng thái prompt');
      fetchPrompts();
    } catch (e) {
      toast.error(`Lỗi khi cập nhật trạng thái: ${e?.message || 'Không xác định'}`);
    }
  };

  return (
    <div style={{ width: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h3 style={{ margin: 0 }}>Quản lý Prompts Theo Chức Năng</h3>
        <button
          onClick={() => handleOpenModal()}
          style={{ padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
        >
          + Thêm mới
        </button>
      </div>

      <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '16px' }}>
        Mỗi chức năng chỉ nên có 1 prompt active. Admin root có thể thêm, sửa, xóa và đổi prompt theo từng chức năng backend.
      </p>

      <div className={styles.tableWrapper}>
        <table className={styles.adminTable} style={{ tableLayout: 'fixed', width: '100%', wordBreak: 'break-word' }}>
          <thead>
            <tr>
              <th style={{ width: '20%' }}>Chức năng</th>
              <th style={{ width: '16%' }}>Định danh</th>
              <th style={{ width: '24%' }}>Nội dung vắn tắt</th>
              <th style={{ width: '20%' }}>Mô tả</th>
              <th style={{ width: '8%' }}>Trạng thái</th>
              <th style={{ width: '12%' }}>Hành động</th>
            </tr>
          </thead>
          <tbody>
            {prompts.length === 0 ? (
              <tr><td colSpan="6" style={{ textAlign: 'center', padding: '20px' }}>Chưa có prompt nào</td></tr>
            ) : prompts.map((p) => (
              <tr key={p.id}>
                <td style={{ fontSize: '0.85rem', padding: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={getFeatureLabel(p.feature_key)}>
                  {getFeatureLabel(p.feature_key)}
                </td>
                <td style={{ fontWeight: 700, color: '#2563eb', fontSize: '0.8rem', padding: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.name}>
                  {p.name}
                </td>
                <td style={{ padding: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.content}>
                  {(() => {
                    if (!p.content) return '';
                    const cleanText = String(p.content).replace(/<[^>]*>?/gm, '').replace(/&nbsp;|\u00A0/g, ' ');
                    const words = cleanText.trim().split(/[\s,]+/);
                    return words.length <= 5 ? cleanText : words.slice(0, 5).join(' ') + '...';
                  })()}
                </td>
                <td style={{ fontSize: '0.85rem', padding: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.description}>
                  {(() => {
                    if (!p.description) return '';
                    const cleanText = String(p.description).replace(/<[^>]*>?/gm, '').replace(/&nbsp;|\u00A0/g, ' ');
                    const words = cleanText.trim().split(/[\s,]+/);
                    return words.length <= 5 ? cleanText : words.slice(0, 5).join(' ') + '...';
                  })()}
                </td>
                <td style={{ padding: '8px' }}>
                  <div 
                    onClick={() => handleToggleActive(p)}
                    style={{
                      width: '44px',
                      height: '24px',
                      borderRadius: '12px',
                      background: p.is_active ? '#10b981' : '#475569',
                      position: 'relative',
                      cursor: 'pointer',
                      transition: 'background 0.3s',
                      margin: '0 auto',
                    }}
                    title={p.is_active ? 'Đang kích hoạt' : 'Tạm dừng'}
                  >
                    <div 
                      style={{
                        width: '20px',
                        height: '20px',
                        borderRadius: '50%',
                        background: '#ffffff',
                        position: 'absolute',
                        top: '2px',
                        left: p.is_active ? '22px' : '2px',
                        transition: 'left 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                      }}
                    />
                  </div>
                </td>
                <td style={{ padding: '8px' }}>
                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                    <button onClick={() => handleOpenModal(p)} className={styles.actionBtnSmall}>Sửa</button>
                    <button onClick={() => handleDelete(p.id)} className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}>Xóa</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--bg-main)', padding: '24px', borderRadius: '16px', width: '100%', maxWidth: '760px', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
            <h4 style={{ margin: '0 0 20px 0' }}>{editingPrompt ? 'Sửa Prompt' : 'Thêm Prompt mới'}</h4>
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Chức năng backend</label>
                <select
                  value={formData.feature_key}
                  onChange={(e) => setFormData({ ...formData, feature_key: e.target.value })}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                  required
                >
                  {(promptFeatures.length ? promptFeatures : fallbackFeatures).map((item) => (
                    <option key={item.feature_key} value={item.feature_key}>
                      {item.label} ({item.feature_key})
                    </option>
                  ))}
                </select>
                <small style={{ color: '#94a3b8' }}>
                  Prompt active của chức năng này sẽ được backend dùng trực tiếp để gọi LLM.
                </small>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Tên định danh (duy nhất)</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                  required
                  disabled={!!editingPrompt}
                />
                {editingPrompt && <small style={{ color: '#94a3b8' }}>Không thể đổi định danh sau khi tạo.</small>}
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Mô tả ngắn</label>
                <input
                  type="text"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Nội dung Prompt</label>
                <textarea
                  value={formData.content}
                  onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit', minHeight: '260px', fontFamily: 'monospace', fontSize: '0.9rem' }}
                  required
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={formData.is_active}
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                  id="is_active_prompt"
                />
                <label htmlFor="is_active_prompt" style={{ fontSize: '0.9rem' }}>Kích hoạt prompt này</label>
              </div>

              <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                <button type="submit" style={{ flex: 1, padding: '10px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Lưu thay đổi</button>
                <button type="button" onClick={() => setIsModalOpen(false)} style={{ flex: 1, padding: '10px', background: '#f1f5f9', color: '#475569', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Hủy</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}


function WebSourceManagement({ styles, onClose }) {
  const [rules, setRules] = useState([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [formData, setFormData] = useState({
    rule_type: 'allow',
    match_type: 'domain',
    value: '',
    note: '',
    is_active: true,
  });

  const rawApiBase = process.env.NEXT_PUBLIC_API_URL || '';
  const API_BASE = rawApiBase.replace(/\/$/, '');
  const buildAdminUrl = (path) => (API_BASE ? `${API_BASE}${path}` : path);

  const requestAdminApi = async (path, options = {}) => {
    const res = await fetch(buildAdminUrl(path), {
      credentials: 'include',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.headers || {}),
      },
    });

    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw {
        status: res.status,
        message: payload?.detail || payload?.message || `HTTP ${res.status}`,
      };
    }
    return payload;
  };

  const fetchRules = async (isInitial = false) => {
    try {
      const data = await requestAdminApi('/api/v1/admin/settings/web-sources');
      setRules(Array.isArray(data) ? data : []);
    } catch (e) {
      if (isInitial && e.status === 404) return;
      toast.error(`Lỗi tải nguồn web: ${e?.message || 'Không xác định'}`);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => fetchRules(true), 0);
    return () => clearTimeout(timer);
  }, []);

  const openModal = (rule = null) => {
    if (rule) {
      setEditingRule(rule);
      setFormData({
        rule_type: rule.rule_type || 'allow',
        match_type: rule.match_type || 'domain',
        value: rule.value || '',
        note: rule.note || '',
        is_active: !!rule.is_active,
      });
    } else {
      setEditingRule(null);
      setFormData({
        rule_type: 'allow',
        match_type: 'domain',
        value: '',
        note: '',
        is_active: true,
      });
    }
    setIsModalOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = {
      rule_type: formData.rule_type,
      match_type: formData.match_type,
      value: formData.value,
      note: formData.note,
      is_active: !!formData.is_active,
    };

    try {
      if (editingRule) {
        await requestAdminApi(`/api/v1/admin/settings/web-sources/${editingRule.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        toast.success('Đã cập nhật rule nguồn web');
      } else {
        await requestAdminApi('/api/v1/admin/settings/web-sources', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        toast.success('Đã thêm rule nguồn web');
      }
      setIsModalOpen(false);
      fetchRules();
    } catch (err) {
      toast.error(`Lỗi: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Bạn có chắc muốn xóa rule này?')) return;
    try {
      await requestAdminApi(`/api/v1/admin/settings/web-sources/${id}`, { method: 'DELETE' });
      toast.success('Đã xóa rule');
      fetchRules();
    } catch (err) {
      toast.error(`Lỗi xóa rule: ${err?.message || 'Không xác định'}`);
    }
  };

  const handleToggleActive = async (rule) => {
    try {
      await requestAdminApi(`/api/v1/admin/settings/web-sources/${rule.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !rule.is_active }),
      });
      toast.success('Đã cập nhật trạng thái rule');
      fetchRules();
    } catch (err) {
      toast.error(`Lỗi cập nhật: ${err?.message || 'Không xác định'}`);
    }
  };

  return (
    <div style={{ width: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h3 style={{ margin: 0, color: 'var(--text-main)' }}>Quản lý Nguồn Web</h3>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            onClick={() => openModal()}
            style={{ padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
          >
            + Thêm website
          </button>
          {onClose && (
            <button
              onClick={onClose}
              style={{
                border: '1px solid var(--border-color)',
                background: 'transparent',
                color: 'var(--text-main)',
                borderRadius: '8px',
                padding: '8px 16px',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              Đóng
            </button>
          )}
        </div>
      </div>

      <div className={styles.tableWrapper}>
        <table className={styles.adminTable} style={{ tableLayout: 'fixed', width: '100%', wordBreak: 'break-word' }}>
          <thead>
            <tr>
              <th style={{ width: '14%' }}>Trạng thái</th>
              <th style={{ width: '14%' }}>Phương thức</th>
              <th style={{ width: '24%' }}>Tên miền</th>
              <th style={{ width: '24%' }}>Ghi chú</th>
              <th style={{ width: '10%' }}>Active</th>
              <th style={{ width: '14%' }}>Hành động</th>
            </tr>
          </thead>
          <tbody>
            {rules.length === 0 ? (
              <tr><td colSpan="6" style={{ textAlign: 'center', padding: '20px' }}>Chưa có rule nguồn web</td></tr>
            ) : rules.map((r) => (
              <tr key={r.id}>
                <td style={{ padding: '8px' }}>
                  <span style={{
                    padding: '3px 7px', borderRadius: '4px', fontSize: '0.75rem',
                    background: r.rule_type === 'allow' ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                    color: r.rule_type === 'allow' ? '#10b981' : '#ef4444',
                    border: `1px solid ${r.rule_type === 'allow' ? '#10b981' : '#ef4444'}`,
                  }}>
                    {r.rule_type === 'allow' ? 'Cho phép' : 'Chặn'}
                  </span>
                </td>
                <td style={{ padding: '8px' }}>{r.match_type === 'domain' ? 'Tên miền' : 'URL chi tiết'}</td>
                <td style={{ padding: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.value}>{r.value}</td>
                <td style={{ padding: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.note || ''}>{r.note || ''}</td>
                <td style={{ padding: '8px' }}>
                  <div
                    onClick={() => handleToggleActive(r)}
                    style={{
                      width: '44px', height: '24px', borderRadius: '12px',
                      background: r.is_active ? '#10b981' : '#475569', position: 'relative',
                      cursor: 'pointer', transition: 'background 0.3s', margin: '0 auto',
                    }}
                  >
                    <div
                      style={{
                        width: '20px', height: '20px', borderRadius: '50%', background: '#ffffff',
                        position: 'absolute', top: '2px', left: r.is_active ? '22px' : '2px',
                        transition: 'left 0.3s cubic-bezier(0.4, 0, 0.2, 1)', boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                      }}
                    />
                  </div>
                </td>
                <td style={{ padding: '8px' }}>
                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                    <button onClick={() => openModal(r)} className={styles.actionBtnSmall}>Sửa</button>
                    <button onClick={() => handleDelete(r.id)} className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}>Xóa</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--bg-main)', padding: '24px', borderRadius: '16px', width: '100%', maxWidth: '700px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
            <h4 style={{ margin: '0 0 20px 0' }}>{editingRule ? 'Sửa website nguồn' : 'Thêm website nguồn'}</h4>
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Trạng thái</label>
                  <select value={formData.rule_type} onChange={(e) => setFormData({ ...formData, rule_type: e.target.value })} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'var(--bg-main)', color: 'var(--text-main)' }}>
                    <option value="allow" style={{ background: '#212121', color: '#ececec' }}>Cho phép</option>
                    <option value="block" style={{ background: '#212121', color: '#ececec' }}>Chặn</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Phương thức</label>
                  <select value={formData.match_type} onChange={(e) => setFormData({ ...formData, match_type: e.target.value })} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'var(--bg-main)', color: 'var(--text-main)' }}>
                    <option value="domain" style={{ background: '#212121', color: '#ececec' }}>Tên miền</option>
                    <option value="url_prefix" style={{ background: '#212121', color: '#ececec' }}>URL chi tiết</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  Tên miền ({formData.match_type === 'domain' ? 'example.com' : 'https://example.com/news'})
                </label>
                <input
                  type="text"
                  value={formData.value}
                  onChange={(e) => setFormData({ ...formData, value: e.target.value })}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                  required
                />
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Ghi chú</label>
                <input
                  type="text"
                  value={formData.note}
                  onChange={(e) => setFormData({ ...formData, note: e.target.value })}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input type="checkbox" checked={formData.is_active} onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })} id="is_active_web_source" />
                <label htmlFor="is_active_web_source" style={{ fontSize: '0.9rem' }}>Kích hoạt website</label>
              </div>

              <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                <button type="submit" style={{ flex: 1, padding: '10px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Lưu</button>
                <button type="button" onClick={() => setIsModalOpen(false)} style={{ flex: 1, padding: '10px', background: 'var(--color-box-input)', color: 'var(--text-main)', border: '1px solid var(--border-color)', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Hủy</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * --- MODEL SETTINGS COMPONENT ---
 */
function ModelSettings({ styles, selectedModel, setSelectedModel, onModelsRefresh }) {
  const [models, setModels] = useState([]);
  const [providers, setProviders] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [loadingProviders, setLoadingProviders] = useState(false);

  const [isProviderModalOpen, setIsProviderModalOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState(null);
  const [providerForm, setProviderForm] = useState({
    name: '',
    provider_type: 'openai_compatible',
    base_url: '',
    api_key: '',
    models: [''],
    description: '',
    is_active: true,
    is_default: false,
  });

  const rawApiBase = process.env.NEXT_PUBLIC_API_URL || '';
  const API_BASE = rawApiBase.replace(/\/$/, '');
  const buildAdminUrl = (path) => (API_BASE ? `${API_BASE}${path}` : path);

  const requestAdminApi = async (path, options = {}) => {
    const res = await fetch(buildAdminUrl(path), {
      credentials: 'include',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.headers || {}),
      },
    });

    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw {
        status: res.status,
        message: payload?.detail || payload?.message || `HTTP ${res.status}`,
      };
    }
    return payload;
  };

  const parseModelsText = (text) => {
    return String(text || '')
      .split(/[\n,]/)
      .map((x) => x.trim())
      .filter(Boolean);
  };

  const fetchModels = async () => {
    setLoadingModels(true);
    try {
      const data = await getRagModels();
      setModels(Array.isArray(data?.models) ? data.models : []);
    } catch (e) {
      console.error('Model list error:', e);
      toast.error('Lỗi khi tải danh sách model runtime');
    } finally {
      setLoadingModels(false);
    }
  };

  const fetchProviders = async () => {
    setLoadingProviders(true);
    try {
      const data = await requestAdminApi('/api/v1/admin/settings/llm-providers');
      setProviders(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error('Providers list error:', e);
      toast.error(`Lỗi khi tải providers: ${e?.message || 'Không xác định'}`);
    } finally {
      setLoadingProviders(false);
    }
  };

  const refreshAll = async () => {
    await Promise.all([fetchModels(), fetchProviders()]);
    if (onModelsRefresh) {
      await onModelsRefresh();
    }
  };

  useEffect(() => {
    refreshAll();
  }, []);

  const handleOpenProviderModal = (provider = null) => {
    if (provider) {
      setEditingProvider(provider);
      setProviderForm({
        name: provider.name || '',
        provider_type: provider.provider_type || 'openai_compatible',
        base_url: provider.base_url || '',
        api_key: provider.api_key || '',
        models: Array.isArray(provider.models) && provider.models.length > 0 ? [...provider.models] : [''],
        description: provider.description || '',
        is_active: !!provider.is_active,
        is_default: !!provider.is_default,
      });
    } else {
      setEditingProvider(null);
      setProviderForm({
        name: '',
        provider_type: 'openai_compatible',
        base_url: '',
        api_key: '',
        models: [''],
        description: '',
        is_active: true,
        is_default: false,
      });
    }
    setIsProviderModalOpen(true);
  };

  const handleSubmitProvider = async (e) => {
    e.preventDefault();

    const payload = {
      name: providerForm.name,
      provider_type: providerForm.provider_type,
      base_url: providerForm.base_url,
      api_key: providerForm.api_key,
      models: providerForm.models.map(m => m.trim()).filter(Boolean),
      description: providerForm.description,
      is_active: !!providerForm.is_active,
      is_default: !!providerForm.is_default,
    };

    try {
      if (editingProvider) {
        await requestAdminApi(`/api/v1/admin/settings/llm-providers/${editingProvider.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        toast.success('Đã cập nhật provider');
      } else {
        await requestAdminApi('/api/v1/admin/settings/llm-providers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        toast.success('Đã thêm provider mới');
      }

      setIsProviderModalOpen(false);
      await refreshAll();
    } catch (e) {
      toast.error(`Lỗi provider: ${e?.message || 'Không xác định'}`);
    }
  };

  const handleDeleteProvider = async (providerId) => {
    if (!window.confirm('Bạn có chắc muốn xóa provider này?')) return;
    try {
      await requestAdminApi(`/api/v1/admin/settings/llm-providers/${providerId}`, { method: 'DELETE' });
      toast.success('Đã xóa provider');
      await refreshAll();
    } catch (e) {
      toast.error(`Lỗi khi xóa provider: ${e?.message || 'Không xác định'}`);
    }
  };

  const handleToggleProviderActive = async (provider) => {
    try {
      await requestAdminApi(`/api/v1/admin/settings/llm-providers/${provider.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !provider.is_active }),
      });
      toast.success('Đã cập nhật trạng thái provider');
      await refreshAll();
    } catch (e) {
      toast.error(`Lỗi cập nhật trạng thái: ${e?.message || 'Không xác định'}`);
    }
  };

  const handleSetDefaultProvider = async (provider) => {
    try {
      await requestAdminApi(`/api/v1/admin/settings/llm-providers/${provider.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_default: true }),
      });
      toast.success('Đã đặt provider mặc định');
      await refreshAll();
    } catch (e) {
      toast.error(`Lỗi đặt mặc định: ${e?.message || 'Không xác định'}`);
    }
  };

  return (
    <div style={{ width: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h4 style={{ margin: 0 }}>Quản Trị Provider (Local/API)</h4>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            onClick={refreshAll}
            className={styles.refreshBtn}
            style={{ padding: '6px 12px', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '6px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"></path></svg>
            Làm mới
          </button>
          <button
            onClick={() => handleOpenProviderModal()}
            style={{ padding: '8px 16px', background: '#2563eb', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}
          >
            + Thêm Provider
          </button>
        </div>
      </div>

      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '14px' }}>
        Gợi ý API chuẩn OpenAI: OpenRouter, Groq, Together, Fireworks. Bạn có thể thêm/xóa/sửa provider để mở rộng model không cần sửa code backend.
      </p>

      <div className={styles.tableWrapper} style={{ marginBottom: '24px' }}>
        <table className={styles.adminTable} style={{ tableLayout: 'fixed', width: '100%', wordBreak: 'break-word' }}>
          <thead>
            <tr>
              <th style={{ width: '15%' }}>Tên Provider</th>
              <th style={{ width: '15%' }}>Loại</th>
              <th style={{ width: '20%' }}>Base URL</th>
              <th style={{ width: '20%' }}>Models</th>
              <th style={{ width: '10%' }}>Mặc định</th>
              <th style={{ width: '8%' }}>Trạng thái</th>
              <th style={{ width: '12%' }}>Hành động</th>
            </tr>
          </thead>
          <tbody>
            {loadingProviders ? (
              <tr><td colSpan="7" style={{ textAlign: 'center', padding: '20px' }}>Đang tải provider...</td></tr>
            ) : providers.length === 0 ? (
              <tr><td colSpan="7" style={{ textAlign: 'center', padding: '20px' }}>Chưa có provider nào</td></tr>
            ) : providers.map((p) => (
              <tr key={p.id}>
                <td style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '8px' }} title={p.name}>{p.name}</td>
                <td style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '8px' }} title={p.provider_type === 'local_vllm' ? 'Local vLLM' : 'OpenAI-Compatible API'}>{p.provider_type === 'local_vllm' ? 'Local vLLM' : 'OpenAI-Compatible API'}</td>
                <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '8px' }} title={p.base_url}>{p.base_url}</td>
                <td style={{ fontSize: '0.8rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '8px' }} title={Array.isArray(p.models) ? p.models.join(', ') : ''}>{Array.isArray(p.models) ? p.models.join(', ') : ''}</td>
                <td style={{ padding: '8px' }}>
                  <span style={{
                    padding: '3px 7px', borderRadius: '4px', fontSize: '0.75rem',
                    background: p.is_default ? 'rgba(37, 99, 235, 0.12)' : 'rgba(148, 163, 184, 0.1)',
                    color: p.is_default ? '#2563eb' : '#94a3b8',
                    border: `1px solid ${p.is_default ? '#2563eb' : '#94a3b8'}`,
                  }}>
                    {p.is_default ? 'Mặc định' : '---'}
                  </span>
                </td>
                <td style={{ padding: '8px' }}>
                  <div 
                    onClick={() => handleToggleProviderActive(p)}
                    style={{
                      width: '44px',
                      height: '24px',
                      borderRadius: '12px',
                      background: p.is_active ? '#10b981' : '#475569',
                      position: 'relative',
                      cursor: 'pointer',
                      transition: 'background 0.3s',
                      margin: '0 auto',
                    }}
                    title={p.is_active ? 'Active' : 'Inactive'}
                  >
                    <div 
                      style={{
                        width: '20px',
                        height: '20px',
                        borderRadius: '50%',
                        background: '#ffffff',
                        position: 'absolute',
                        top: '2px',
                        left: p.is_active ? '22px' : '2px',
                        transition: 'left 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                      }}
                    />
                  </div>
                </td>
                <td style={{ padding: '8px' }}>
                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                    <button onClick={() => handleOpenProviderModal(p)} className={styles.actionBtnSmall}>Sửa</button>
                    {!p.is_default && (
                      <button onClick={() => handleSetDefaultProvider(p)} className={styles.actionBtnSmall}>Đặt mặc định</button>
                    )}
                    <button onClick={() => handleDeleteProvider(p.id)} className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}>Xóa</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h3 style={{ margin: 0 }}>Model Runtime (Local/API)</h3>
      </div>

      <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '20px' }}>
        Danh sách model bên dưới hiển thị model Local vLLM hoặc API chuẩn OpenAI. Khi user đổi model, hệ thống sẽ gửi request tới đúng provider tương ứng.
      </p>

      <div className={styles.tableWrapper}>
        <table className={styles.adminTable} style={{ tableLayout: 'fixed', width: '100%', wordBreak: 'break-word' }}>
          <thead>
            <tr>
              <th style={{ width: '25%' }}>Tên Model</th>
              <th style={{ width: '25%' }}>Nguồn / Provider</th>
              <th style={{ width: '20%' }}>Base URL</th>
              <th style={{ width: '15%' }}>Trạng thái</th>
              <th style={{ width: '15%' }}>Hành động</th>
            </tr>
          </thead>
          <tbody>
            {loadingModels ? (
              <tr><td colSpan="5" style={{ textAlign: 'center', padding: '20px' }}>Đang tải...</td></tr>
            ) : (models && models.length === 0) ? (
              <tr><td colSpan="5" style={{ textAlign: 'center', padding: '20px' }}>Không tìm thấy model runtime nào</td></tr>
            ) : models.map((m) => (
              <tr key={m.id}>
                <td style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '8px' }} title={m.display_name || m.model_name}>{m.display_name || m.model_name}</td>
                <td style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '8px' }} title={`${m.source_label} (${m.provider_name})`}>{m.source_label} ({m.provider_name})</td>
                <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: '8px' }} title={m.base_url}>{m.base_url}</td>
                <td style={{ padding: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {m.id === selectedModel ? (
                    <span style={{ padding: '4px 8px', background: '#10b981', color: 'white', borderRadius: '4px', fontSize: '0.8rem' }}>Đang dùng</span>
                  ) : (
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Sẵn sàng</span>
                  )}
                </td>
                <td style={{ textAlign: 'right', padding: '8px' }}>
                  <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                    <button
                      disabled={m.id === selectedModel}
                      onClick={() => {
                        setSelectedModel(m.id);
                        toast.success(`Đã chọn model: ${m.display_name || m.model_name}`);
                      }}
                      className={styles.actionBtnSmall}
                      style={{ opacity: m.id === selectedModel ? 0.5 : 1 }}
                    >
                      Chọn dùng
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isProviderModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--bg-main)', padding: '24px', borderRadius: '16px', width: '100%', maxWidth: '760px', maxHeight: '92vh', overflowY: 'auto', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
            <h4 style={{ margin: '0 0 16px 0' }}>{editingProvider ? 'Sửa Provider' : 'Thêm Provider Mới'}</h4>
            <form onSubmit={handleSubmitProvider} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Tên Provider</label>
                  <input
                    type="text"
                    value={providerForm.name}
                    onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })}
                    style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                    required
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Loại Provider</label>
                  <select
                    value={providerForm.provider_type}
                    onChange={(e) => setProviderForm({ ...providerForm, provider_type: e.target.value })}
                    style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                  >
                    <option value="local_vllm">Local vLLM</option>
                    <option value="openai_compatible">OpenAI-Compatible API</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Base URL</label>
                <input
                  type="text"
                  value={providerForm.base_url}
                  onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
                  placeholder={providerForm.provider_type === 'local_vllm' ? 'http://192.168.2.74:8007/v1' : 'https://api.example.com/v1'}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>API Key (Hệ thống sẽ lấy tự động nếu truyền biến .env)</label>
                  <input
                    type="password"
                    value={providerForm.api_key}
                    onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })}
                    placeholder={editingProvider ? 'Để trống nếu giữ nguyên. Form này tự lấy biến .env (vd: OPENAI_API_KEY)' : 'Nhập API key trực tiếp hoặc điền biến môi trường .env (Ví dụ: KHANH_DEEPSEEK_KEY)'}
                    style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Danh sách Models</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {providerForm.models.map((mod, index) => (
                    <div key={index} style={{ display: 'flex', gap: '8px' }}>
                      <input
                        type="text"
                        value={mod}
                        onChange={(e) => {
                          const updated = [...providerForm.models];
                          updated[index] = e.target.value;
                          setProviderForm({ ...providerForm, models: updated });
                        }}
                        placeholder="Ví dụ: gpt-4o"
                        style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                      />
                      <button
                        type="button"
                        onClick={() => {
                          const updated = providerForm.models.filter((_, i) => i !== index);
                          setProviderForm({ ...providerForm, models: updated });
                        }}
                        style={{ padding: '8px 12px', background: '#ef4444', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
                      >
                        Xóa
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => {
                      setProviderForm({ ...providerForm, models: [...providerForm.models, ''] });
                    }}
                    style={{ alignSelf: 'flex-start', padding: '6px 12px', background: '#e2e8f0', color: '#0f172a', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}
                  >
                    + Thêm Model
                  </button>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Mô tả</label>
                <input
                  type="text"
                  value={providerForm.description}
                  onChange={(e) => setProviderForm({ ...providerForm, description: e.target.value })}
                  style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }}
                />
              </div>

              <div style={{ display: 'flex', gap: '20px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input
                    type="checkbox"
                    checked={providerForm.is_active}
                    onChange={(e) => setProviderForm({ ...providerForm, is_active: e.target.checked })}
                  />
                  Active
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input
                    type="checkbox"
                    checked={providerForm.is_default}
                    onChange={(e) => setProviderForm({ ...providerForm, is_default: e.target.checked })}
                  />
                  Đặt làm mặc định
                </label>
              </div>

              <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                <button type="submit" style={{ flex: 1, padding: '10px', background: '#2563eb', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Lưu Provider</button>
                <button type="button" onClick={() => setIsProviderModalOpen(false)} style={{ flex: 1, padding: '10px', background: '#f1f5f9', color: '#475569', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>Hủy</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default function QueryDataPage() {
  const router = useRouter();
  const [isMounted, setIsMounted] = useState(false);
  useEffect(() => {
    setIsMounted(true);
  }, []);
  const [userName, setUserName] = useState('Người dùng');
  const [userId, setUserId] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('userId') || '1';
    }
    return '1';
  });
  const [userEmail, setUserEmail] = useState('');
  const [userPhone, setUserPhone] = useState('');
  const [userAddress, setUserAddress] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [isAvatarUploading, setIsAvatarUploading] = useState(false);
  const avatarInputRef = useRef(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [userRoles, setUserRoles] = useState([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [canRag, setCanRag] = useState(false);
  const [canUpload, setCanUpload] = useState(false);
  const [canCreateContract, setCanCreateContract] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null);

  useEffect(() => {
    setIsAdmin(userRoles.includes('root'));
    setCanRag(userRoles.includes('root') || userRoles.includes('rag'));
    setCanUpload(userRoles.includes('root') || userRoles.includes('upload'));
    const canCreate = userRoles.includes('root') || userRoles.includes('create');
    setCanCreateContract(canCreate);

    if (activeMode === 'query') {
      if (!userRoles.includes('root') && !userRoles.includes('rag')) {
        if (canCreate) {
          setActiveMode('contract');
        }
      }
    }
  }, [userRoles]);
  const messagesEndRef = useRef(null);
  const [history, setHistory] = useState([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [session, setSession] = useState([-1, -1]);
  const [sessionList, setSessionList] = useState([]);
  const [file, setFile] = useState([]);
  const [fileList, setFileList] = useState([]); // templates
  const [template, setTemplate] = useState(["", -1]);
  const [isLoading, setIsLoading] = useState(false);
  const [isFileActionLoading, setIsFileActionLoading] = useState(false);
  const [progressMsg, setProgressMsg] = useState("");
  const [showWelcome, setShowWelcome] = useState(true);
  const [isHoveringToggle, setIsHoveringToggle] = useState(false);

  // Tool Mode: "query" (Truy vấn RAG) hoặc "contract" (Tạo Hợp Đồng)
  const [activeMode, setActiveMode] = useState("query");
  const [activeFlow, setActiveFlow] = useState("fast");
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [editSessionName, setEditSessionName] = useState("");

  // File Manager Modal
  const [isFileManagerOpen, setIsFileManagerOpen] = useState(false);
  const [isWebSourcePanelOpen, setIsWebSourcePanelOpen] = useState(false);
  const [isContractManagerOpen, setIsContractManagerOpen] = useState(false);
  const [contractList, setContractList] = useState([]);

  // States cho Sidebar phong cách ChatGPT
  const [isFileSectionOpen, setIsFileSectionOpen] = useState(false);
  const [isSessionSectionOpen, setIsSessionSectionOpen] = useState(true);

  // Model Selector States
  const [modelSearchQuery, setModelSearchQuery] = useState("");
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false);
  const modelRef = useRef(null);
  const navEsRef = useRef(null);

  // vLLM selection state
  const [vllmModels, setVllmModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");

  const [isProfileDropdownOpen, setIsProfileDropdownOpen] = useState(false);
  const profileRef = useRef(null);

  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [activeSettingsTab, setActiveSettingsTab] = useState("general");
  const { theme, setTheme } = useTheme();
  const [isPersonalInfoExpanded, setIsPersonalInfoExpanded] = useState(false);
  const [isQuickEditSettingsOpen, setIsQuickEditSettingsOpen] = useState(false);
  const [isHelpPopupOpen, setIsHelpPopupOpen] = useState(false);
  const [openHelpSection, setOpenHelpSection] = useState(null);

  const [isSidebarProfileOpen, setIsSidebarProfileOpen] = useState(false);
  const sidebarProfileRef = useRef(null);

  const [isAdminPanelOpen, setIsAdminPanelOpen] = useState(false);
  const [activeAdminTab, setActiveAdminTab] = useState("users");
  const [activeAdminSettingsTab, setActiveAdminSettingsTab] = useState("Models");
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const [analyticsData, setAnalyticsData] = useState({
    users: 0, chats: 0, messages: 0, tokens: 0, files: 0, my_chats: 0, my_messages: 0, my_tokens: 0, my_files: 0
  });
  const [systemMetrics, setSystemMetrics] = useState(null);

  useEffect(() => {
    let interval;
    if (isAdminPanelOpen && activeAdminTab === 'analytics') {
      const fetchAnalytics = async () => {
        try {
          if (isAdmin) {
            const [data, metrics] = await Promise.all([
              getAdminAnalytics(),
              getSystemMetrics()
            ]);
            setAnalyticsData(prev => ({ ...prev, ...data }));
            setSystemMetrics(metrics.metrics);
          } else {
            const data = await getUserAnalytics();
            setAnalyticsData(prev => ({ ...prev, ...data }));
          }
        } catch (e) { 
          console.error("Error fetching analytics", e); 
        }
      }
      
      fetchAnalytics();
      interval = setInterval(fetchAnalytics, 5000); // Tự động cập nhật mỗi 5 giây
    }
    return () => { if (interval) clearInterval(interval); };
  }, [isAdminPanelOpen, activeAdminTab, isAdmin]);

  // Load notifications for admin
  const fetchNotifications = async () => {
    try {
      const res = await getNotifications(20, 0);
      if (res.status === 200 || res.status === 'ok') {
        setNotifications(res.data || []);
        // Note: setting unreadCount based on total if total is returned, otherwise filter
        setUnreadCount(res.total - (res.data || []).filter(n => n.is_read).length);
      }
    } catch (err) {
      console.error("Failed to fetch notifications:", err);
    }
  };

  useEffect(() => {
    if (isAdminPanelOpen && activeAdminTab === 'security') {
      fetchNotifications();
    }
  }, [isAdminPanelOpen, activeAdminTab]);

  const handleSecurityAlert = (alert) => {
    const severityPrefix = alert.severity === 'critical' ? '🔴' : alert.severity === 'high' ? '🟠' : '🟡';
    toast.error(`${severityPrefix} CẢNH BÁO BẢO MẬT: ${alert.title}`, {
      position: "top-right",
      autoClose: 10000,
    });
    if (activeAdminTab === 'security') {
      fetchNotifications();
    }
  };

  const handleMarkAsRead = async (id) => {
    try {
      await markNotificationRead(id);
      fetchNotifications();
    } catch (err) {
      toast.error("Không thể đánh dấu đã đọc.");
    }
  };

  const handleDeactivateFromNotif = async (n) => {
    const label = n.account_name ? `${n.account_name} (${n.account_email || `ID ${n.account_id}`})` : `ID ${n.account_id}`;
    if (!window.confirm(`Khóa tài khoản ${label} do cảnh báo bảo mật?`)) return;
    try {
      await deactivateAccount(n.account_id);
      const label = n.account_name || `ID ${n.account_id}`;
      toast.success(`Đã khóa tài khoản ${label}`);
      if (!n.is_read) await markNotificationRead(n.id).catch(() => { });
      fetchNotifications();
      const data = await getAccounts();
      setAccountsList(data.result || []);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Không thể khóa tài khoản.");
    }
  };

  const handleDeleteNotification = async (id) => {
    try {
      await deleteNotification(id);
      fetchNotifications();
    } catch (err) {
      toast.error("Không thể xóa thông báo.");
    }
  };

  const handleDeleteAllReadNotifications = async () => {
    if (!window.confirm("Xóa tất cả thông báo đã đọc?")) return;
    try {
      const res = await deleteAllReadNotifications();
      toast.success(`Đã xóa ${res.deleted ?? 0} thông báo đã đọc`);
      fetchNotifications();
    } catch (err) {
      toast.error("Không thể xóa thông báo đã đọc.");
    }
  };

  const handleDeleteLoginHistoryEntry = async (entryId) => {
    try {
      await deleteLoginHistoryEntry(entryId);
      setLoginHistory(prev => prev.filter(h => h.id !== entryId));
      toast.success('Đã xóa bản ghi');
    } catch (err) {
      toast.error('Không thể xóa bản ghi.');
    }
  };

  const handleDeleteLoginHistory = async (accountId) => {
    if (!window.confirm("Xóa toàn bộ lịch sử đăng nhập của tài khoản này?")) return;
    try {
      const res = await deleteLoginHistory(accountId);
      toast.success(`Đã xóa ${res.deleted ?? 0} bản ghi lịch sử`);
      setLoginHistory([]);
    } catch (err) {
      toast.error("Không thể xóa lịch sử đăng nhập.");
    }
  };
  const [loginHistory, setLoginHistory] = useState([]);
  const [isLoginHistoryModalOpen, setIsLoginHistoryModalOpen] = useState(false);
  const [selectedUserForHistory, setSelectedUserForHistory] = useState(null);
  const [systemRoles, setSystemRoles] = useState([]);
  const [isRoleModalOpen, setIsRoleModalOpen] = useState(false);
  const [roleActionType, setRoleActionType] = useState('add'); // 'add' or 'remove'
  const [selectedUserForRole, setSelectedUserForRole] = useState(null);

  const closeAllOverlays = useCallback((options = {}) => {
    const { closeAdmin = false } = options;
    setIsFileManagerOpen(false);
    setIsWebSourcePanelOpen(false);
    setIsContractManagerOpen(false);
    setIsSettingsModalOpen(false);
    setIsHelpPopupOpen(false);
    if (closeAdmin) setIsAdminPanelOpen(false);
    setIsRoleModalOpen(false);
    setIsLoginHistoryModalOpen(false);
    setIsQuickEditSettingsOpen(false);
    setIsProfileDropdownOpen(false);
    setIsSidebarProfileOpen(false);
    setIsModelDropdownOpen(false);
    setActiveMenu(null);
  }, []);

  const openSettingsOverlay = useCallback(() => {
    closeAllOverlays({ closeAdmin: true });
    setIsSettingsModalOpen(true);
  }, [closeAllOverlays]);

  const openHelpOverlay = useCallback(() => {
    closeAllOverlays({ closeAdmin: true });
    setIsHelpPopupOpen(true);
  }, [closeAllOverlays]);

  const openAdminOverlay = useCallback((tab = 'users') => {
    closeAllOverlays();
    setActiveAdminTab(tab);
    setIsAdminPanelOpen(true);
  }, [closeAllOverlays]);

  const openFileManagerOverlay = useCallback(() => {
    closeAllOverlays({ closeAdmin: true });
    setIsFileManagerOpen(true);
  }, [closeAllOverlays]);

  const openWebSourceOverlay = useCallback(() => {
    closeAllOverlays({ closeAdmin: true });
    setIsWebSourcePanelOpen(true);
  }, [closeAllOverlays]);

  const openContractManagerOverlay = useCallback(() => {
    closeAllOverlays({ closeAdmin: true });
    setIsContractManagerOpen(true);
  }, [closeAllOverlays]);

  const viewLoginHistory = async (acc) => {
    closeAllOverlays();
    setSelectedUserForHistory(acc);
    setIsLoginHistoryModalOpen(true);
    setLoginHistory([]); // Loading state
    try {
      const res = await getLoginHistory(acc.id, 50, 0);
      if (res.status === 200 || res.status === 'ok') {
        setLoginHistory(res.data || []);
      }
    } catch (err) {
      console.error("Failed to fetch login history:", err);
    }
  };

  const handleDeleteAccount = async (acc) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xóa vĩnh viễn tài khoản ${acc.email}? Hành động này không thể hoàn tác.`)) {
      return;
    }
    try {
      await deleteAccount(acc.id);
      toast.success(`Đã xóa tài khoản ${acc.email}`);
      // Refresh list
      const data = await getAccounts();
      setAccountsList(data.result || []);
    } catch (err) {
      toast.error("Xóa tài khoản thất bại.");
    }
  };

  const handleToggleActive = async (acc) => {
    try {
      if (acc.is_active) {
        await deactivateAccount(acc.id);
        toast.info(`Đã khóa tài khoản ${acc.email}`);
      } else {
        await activateAccount(acc.id);
        toast.success(`Đã kích hoạt tài khoản ${acc.email}`);
      }
      // Refresh list
      const data = await getAccounts();
      setAccountsList(data.result || []);
    } catch (err) {
      toast.error("Thao tác thất bại.");
    }
  };

  const handleChangeRole = async (acc, newRoles) => {
    try {
      await updateRoles(acc.id, newRoles);
      toast.success(`Đã cập nhật quyền cho ${acc.email}`);
      // Refresh list
      const data = await getAccounts();
      setAccountsList(data.result || []);
    } catch (err) {
      console.error("Update role error:", err);
      const msg = err.response?.data?.detail || "Cập nhật quyền thất bại.";
      toast.error(msg);
    }
  };

  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDesc, setNewRoleDesc] = useState("");

  const handleCreateRole = async () => {
    if (!newRoleName) return toast.warning("Vui lòng nhập tên Role");
    try {
      await createRole(newRoleName, newRoleDesc);
      // Re-fetch roles
      const rolesData = await getRoles();
      setSystemRoles(rolesData.result || []);
      setNewRoleName("");
      setNewRoleDesc("");
      toast.success("Đã tạo Role mới");
    } catch (err) {
      toast.error("Không thể tạo Role");
    }
  };

  const refreshAvailableModels = async () => {
    try {
      const res = await getRagModels();
      let items = Array.isArray(res?.models) ? res.models : [];
      // Backward compatibility: map strings to objects if backend returns old format
      items = items.map(m => typeof m === 'string' ? { 
        id: m, model_name: m, display_name: m.split('/').pop(), source_label: 'Local vLLM', provider_name: 'Unknown'
      } : m);
      
      setVllmModels(items);

      if (items.length === 0) {
        setSelectedModel("");
        return;
      }

      if (!items.some((m) => m.id === selectedModel)) {
        if (items.length > 0) {
          setSelectedModel(items[0].id);
        }
      }
    } catch (e) {
      console.error("Error fetching runtime models:", e);
    }
  };

  useEffect(() => {
    refreshAvailableModels();
  }, []);

  const selectedModelMeta = vllmModels.find((m) => m.id === selectedModel) || null;

  const handleNavbarModelSwitch = (modelId) => {
    setSelectedModel(modelId);
    setIsModelDropdownOpen(false);
    const meta = vllmModels.find((m) => m.id === modelId);
    const mName = meta?.display_name || meta?.model_name || modelId;
    const sourceName = meta ? ` (${meta.source_label} - ${meta.provider_name})` : "";
    toast.success(`Đã chọn model: ${mName}${sourceName}`);
  };

  const [accountsList, setAccountsList] = useState([]);
  const [contractPinnedIds, setContractPinnedIds] = useState([]);

  // Fetch system roles when admin panel opens
  useEffect(() => {
    if (isAdminPanelOpen && isAdmin) {
      const fetchRoles = async () => {
        try {
          const data = await getRoles();
          setSystemRoles(data.result || []);
        } catch (err) {
          console.error("Failed to fetch system roles:", err);
        }
      };
      fetchRoles();
    }
  }, [isAdminPanelOpen, isAdmin]);

  const modelOptions = [
    { id: "khazarai/Qwen3-4B-Qwen3.6-plus-Reasoning-Distilled", name: "Qwen3 4B Reasoning", tag: "Cục Bộ" },
    // { id: "gemini-2-flash", name: "Gemini 2.0 Flash", tag: "Nhanh" },
    // { id: "gemini-2-pro", name: "Gemini 2.0 Pro", tag: "Thông minh" },
    // { id: "gpt-4o", name: "GPT-4o", tag: "Đa năng" },
    // { id: "gpt-4-turbo", name: "GPT-4 Turbo", tag: "Mạnh mẽ" },
    // { id: "claude-3-5-sonnet", name: "Claude 3.5 Sonnet", tag: "Sáng tạo" }
  ];

  // Admin: hiển thị tất cả model cache vLLM; người dùng thường: dùng modelOptions tĩnh
  const navbarModelOptions = vllmModels.length > 0
    ? vllmModels.map(m => ({ id: m.id, name: m.display_name || m.model_name, tag: `${m.source_label} - ${m.provider_name}` }))
    : [{ id: "1::Qwen/Qwen2.5-VL-7B-Instruct-FP8", name: "Qwen2.5 7B", tag: "Mặc định" }];

  // Sidebar Context Menu State
  const [activeMenu, setActiveMenu] = useState(null); // { type: 'file' | 'session', index: number }
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [hasSidebarScroll, setHasSidebarScroll] = useState(false);
  const sidebarContentRef = useRef(null);

  // Close dropdowns when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (modelRef.current && !modelRef.current.contains(event.target)) {
        setIsModelDropdownOpen(false);
      }
      if (profileRef.current && !profileRef.current.contains(event.target)) {
        setIsProfileDropdownOpen(false);
      }
      if (sidebarProfileRef.current && !sidebarProfileRef.current.contains(event.target)) {
        setIsSidebarProfileOpen(false);
      }
      if (!event.target.closest(`.${styles.menuBtn}`) && !event.target.closest(`.${styles.dropdownMenu}`)) {
        setActiveMenu(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Check for sidebar scroll to show dynamic border
  useEffect(() => {
    const checkScroll = () => {
      if (sidebarContentRef.current && isSidebarOpen) {
        const { scrollHeight, clientHeight } = sidebarContentRef.current;
        setHasSidebarScroll(scrollHeight > clientHeight);
      } else {
        setHasSidebarScroll(false);
      }
    };

    checkScroll();

    // Re-check when content changes
    const observer = new ResizeObserver(checkScroll);
    if (sidebarContentRef.current) {
      observer.observe(sidebarContentRef.current);
    }

    // Also check on sidebar items update
    window.addEventListener('resize', checkScroll);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', checkScroll);
    };
  }, [file, sessionList, isSidebarOpen, isFileSectionOpen, isSessionSectionOpen]);

  useEffect(() => {
    // Auth guard: kiểm tra phiên đăng nhập
    const checkAuth = async () => {
      try {
        const data = await getMe();
        const account = data.result;
        setUserName(account.name || 'Người dùng');
        setUserId(String(account.id));
        setUserEmail(account.email || '');
        setUserPhone(account.phone || '');
        setUserAddress(account.address || '');
        if (account.has_avatar) {
          setAvatarUrl(`${getAvatarUrl(account.id)}?t=${Date.now()}`);
        } else {
          setAvatarUrl('');
        }

        localStorage.setItem('userName', account.name || 'Người dùng');
        localStorage.setItem('userId', String(account.id));
        localStorage.setItem('userEmail', account.email);
        localStorage.setItem('userPhone', account.phone || '');
        localStorage.setItem('userAddress', account.address || '');

        if (account.roles) {
          setUserRoles(account.roles);
          localStorage.setItem('userRoles', JSON.stringify(account.roles));
        }
      } catch (err) {
        const status = err?.response?.status;
        // 401 hoặc 403 (bị khóa/chưa active) → xóa cache + redirect login
        if (status === 401 || status === 403) {
          localStorage.removeItem('userName');
          localStorage.removeItem('userId');
          localStorage.removeItem('userRoles');
          localStorage.removeItem('userEmail');
          const detail = err.response?.data?.detail || 'Phiên đăng nhập đã hết hạn.';
          window.location.href = `/signin?reason=${encodeURIComponent(detail)}`;
          return;
        }
        // Lỗi mạng / server — fallback localStorage để không mất trải nghiệm
        const storedName = localStorage.getItem('userName');
        if (storedName) {
          setUserName(storedName);
        }
        const storedRoles = localStorage.getItem('userRoles');
        if (storedRoles) {
          try { setUserRoles(JSON.parse(storedRoles)); } catch (e) { /* ignore */ }
        }
      }
    };
    checkAuth();
  }, []);


  useEffect(() => {
    try {
      const stored = localStorage.getItem('contractPinnedIds');
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        const ids = parsed.map((id) => Number(id)).filter((id) => Number.isFinite(id));
        setContractPinnedIds(ids);
      }
    } catch (_) {
      // ignore localStorage parsing errors
    }
  }, []);

  useEffect(() => {
    localStorage.setItem('contractPinnedIds', JSON.stringify(contractPinnedIds));
  }, [contractPinnedIds]);

  // Load danh sách accounts khi mở admin panel
  useEffect(() => {
    let intervalId = null;

    if (isAdminPanelOpen && isAdmin) {
      const fetchAccounts = async () => {
        try {
          const data = await getAccounts();
          const accounts = data.result || [];

          // Kiểm tra trạng thái online qua heartbeat
          const userIds = accounts.map(a => a.id);
          if (userIds.length > 0) {
            try {
              const onlineRes = await heartbeatCheck(userIds);
              if (onlineRes.status === 'ok') {
                // Sửa logic: lấy kết quả từ .data.result theo format backend thực tế
                const onlineMap = onlineRes.data?.result || {};
                const updatedAccounts = accounts.map(a => ({
                  ...a,
                  is_online: onlineMap[a.id] || false
                }));
                setAccountsList(updatedAccounts);
                return;
              }
            } catch (err) {
              console.warn('Không thể kiểm tra trạng thái online:', err);
            }
          }
          setAccountsList(accounts);
        } catch (err) {
          console.error('Không thể tải danh sách accounts:', err);
        }
      };

      fetchAccounts();
      // Tự động cập nhật mỗi 30 giây
      intervalId = setInterval(fetchAccounts, 30000);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [isAdminPanelOpen, isAdmin]);

  const getInitials = (name) => {
    if (!name) return 'U';
    const parts = name.trim().split(' ');
    if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
    return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
  };

  const formatRelativeTime = (value) => {
    if (!value) return 'Chưa truy cập';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Chưa truy cập';

    const diffMs = Date.now() - date.getTime();
    if (diffMs <= 0) return 'Vừa xong';

    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return 'Vừa xong';

    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}p trước`;

    const diffHour = Math.floor(diffMin / 60);
    if (diffHour < 24) return `${diffHour}h trước`;

    const diffDay = Math.floor(diffHour / 24);
    if (diffDay < 7) return `${diffDay} ngày trước`;

    return date.toLocaleString('vi-VN');
  };

  const getLastSeenDetails = (acc) => {
    const lines = [];
    if (acc?.last_seen_at) {
      const date = new Date(acc.last_seen_at);
      if (!Number.isNaN(date.getTime())) {
        lines.push(`Thời gian: ${date.toLocaleString('vi-VN')}`);
      }
    }
    if (acc?.last_seen_ip) {
      lines.push(`IP: ${acc.last_seen_ip}`);
    }
    if (acc?.last_seen_location) {
      lines.push(`Địa điểm: ${acc.last_seen_location}`);
    }
    return lines;
  };

  const getHighestRole = (roles) => {
    if (!roles || roles.length === 0) return 'none';
    const hierarchy = ['root', 'admin', 'rag', 'create', 'user', 'upload'];
    for (const r of hierarchy) {
      if (roles.map(x => x.toLowerCase()).includes(r.toLowerCase())) return r;
    }
    return roles[0];
  };

  const buildContractSummary = (result) => {
    if (!result) return "Đã tạo hợp đồng. Bấm vào để tải về.";
    const text = result.summary || result.mess || "Đã tạo hợp đồng. Bấm vào để tải về.";
    const normalized = String(text).trim();
    if (normalized.length <= 500) return normalized;
    return `${normalized.slice(0, 500)}...`;
  };

  const decorateContractSessions = (sessions) => {
    const list = Array.isArray(sessions) ? sessions : [];
    return list.map((item) => {
      if (typeof item === 'object' && item !== null) {
        return { ...item, is_pinned: contractPinnedIds.includes(Number(item.id)) };
      }
      const id = Number(item);
      return {
        id,
        name: `${item}`,
        is_pinned: contractPinnedIds.includes(id),
      };
    });
  };



  const [isStreaming, setIsStreaming] = useState(false);
  const fileActionLockRef = useRef(false);

  const setFileActionBusy = (busy) => {
    fileActionLockRef.current = busy;
    setIsFileActionLoading(busy);
  };

  const runWithFileActionLock = async (task) => {
    if (fileActionLockRef.current) {
      toast.info('Đang xử lý tệp, vui lòng chờ hoàn tất.');
      return null;
    }
    setFileActionBusy(true);
    try {
      return await task();
    } finally {
      setFileActionBusy(false);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };
  // Bỏ auto scroll để người dùng có thể cuộn xem lịch sử

  // Load data khi vào trang hoặc khi đổi mode
  useEffect(() => {
    if (activeMode === "query") {
      loadSession().then((data_) => setSessionList(data_)).catch((err) => console.error('loadSession error:', err));
      loadFile().then((data_) => setFile(data_)).catch((err) => console.error('loadFile error:', err));
    } else {
      contractService.loadSession(userId).then((data_) => setSessionList(decorateContractSessions(data_))).catch((err) => console.error('contract.loadSession error:', err));
      contractService.loadTemplateHome().then((data_) => setFile(data_)).catch((err) => console.error('loadTemplateHome error:', err));
      contractService.loadContract().then((data_) => setContractList(data_ || [])).catch((err) => console.error('loadContract error:', err));
    }
    setTemplate(["", -1]);
  }, [activeMode]);

  useEffect(() => {
    const allowedFlows = activeMode === "contract"
      ? ["fast", "reasoning", "templated"]
      : ["fast", "web_search"];
    if (!allowedFlows.includes(activeFlow)) {
      setActiveFlow("fast");
    }
  }, [activeMode, activeFlow]);

  useEffect(() => {
    if (!isStreaming) {
      scrollToBottom();
    }
  }, [history, isStreaming]);

  // Scroll ngay khi gửi câu hỏi (trước khi bắt đầu stream)
  const scrollToBottomInstant = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "instant" });
  };

  const handleSendMessage = async (text, files = []) => {
    if (isLoading || isStreaming) return;
    if (isFileActionLoading) {
      toast.info('Đang upload/đính kèm tệp, vui lòng chờ xong rồi gửi tin nhắn.');
      return;
    }

    // Log để kiểm tra file đính kèm (Sẽ dùng để tích hợp upload sau này)
    if (files.length > 0) {
      console.log("Files attached:", files.map(f => f.name));
    }

    const currentUserId = userId || localStorage.getItem("userId") || "1";
    if (activeMode === "contract" && activeFlow === "templated" && template[1] === -1) {
      toast.error("Chưa chọn template hợp đồng!");
      return;
    }

    let newItem = {
      id: Date.now(),
      id_user: userId,
      mess: text,
      role: "user",
      session: session[0],
    };
    setHistory((prev) => [...prev, newItem]);
    setIsLoading(true);
    toast.info(activeMode === "query" ? "Đang gửi câu hỏi..." : "Đang tạo hợp đồng...");

    try {
      if (activeMode === "query") {
        setIsLoading(false); // Đóng loading quay quay mạc định

        // Tạo tin nhắn "Bot tạm thời" để append stream
        const tempBotId = Date.now() + 1;
        let botItem = {
          id: tempBotId,
          id_user: userId,
          mess: "",
          role: "bot",
          session: session[0],
          title: "Đang kết nối..."
        };

        // Thêm tin nhắn bot rỗng vào giao diện
        setHistory((prev) => [...prev, botItem]);
        setShowWelcome(false);
        setIsStreaming(true);
        // Scroll xuống ngay để user thấy tin nhắn vừa gửi + bot placeholder
        setTimeout(() => scrollToBottomInstant(), 0);

        // Ưu tiên sử dụng model đang chạy trên server cho tất cả người dùng
        const modelIdToPass = selectedModel || vllmModels[0]?.id || "Qwen/Qwen2.5-VL-7B-Instruct-FP8";

        await sendQueryStream(session[0], text, modelIdToPass, activeFlow, async (parsedData) => {
          // Callback chạy liên tục mỗi khi nhận 1 đoạn stream mới
          setHistory(prevHistory => {
            const updatedHistory = [...prevHistory];
            const botMsgIndex = updatedHistory.findIndex(msg => msg.id === tempBotId);

            if (botMsgIndex !== -1) {
              const currentMsg = updatedHistory[botMsgIndex];

              // Chỉ append mess khi đang stream token LLM thật (title = "Đang trả lời...")
              let newMess = currentMsg.mess;
              if (parsedData.mess && parsedData.title === "Đang trả lời...") {
                newMess += parsedData.mess;
              }

              // Cập nhật danh sách file nguồn (merge, không trùng)
              let newSourceFiles = currentMsg.source_files || [];
              if (parsedData.list_file && parsedData.list_file.length > 0) {
                newSourceFiles = [...newSourceFiles, ...parsedData.list_file];
              }

              // Cập nhật title mới
              let newTitle = currentMsg.title;
              if (parsedData.title !== undefined) {
                newTitle = parsedData.title;
              }

              updatedHistory[botMsgIndex] = {
                ...currentMsg,
                mess: newMess,
                title: newTitle,
                source_files: newSourceFiles,
              };
            }
            return updatedHistory;
          });

          // Nếu nhận được tín hiệu kết thúc
          if (parsedData.end === true) {
            // Đồng bộ lại danh sách session nếu đây là cuộc trò chuyện đầu tiên
            const data_ = await loadSession();
            setSessionList(data_);

            let targetSessionId = parsedData.session_id || session[0];
            if (session[0] === -1 && targetSessionId !== -1) {
              // Tìm index của session mới trong danh sách vừa tải lại
              const newIndex = data_.findIndex(s => (s.id || s) === targetSessionId);
              setSession([targetSessionId, newIndex]);
            }

            // Tải lại lịch sử chuẩn từ DB để thay thế đồ giả (đảm bảo ID khớp với Database thật)
            const finalHistory = await loadHistory(targetSessionId);
            setHistory(finalHistory);
            setIsStreaming(false);
            toast.dismiss();
            // toast.success("Hoàn thành!");
          }
        });
        // Safety net: nếu stream kết thúc mà không có end: true
        setIsStreaming(false);

      } else {
        // Mode contract
        // Ưu tiên sử dụng model đang chạy trên server cho tất cả người dùng
        const modelIdToPass = selectedModel || vllmModels[0]?.id || "Qwen/Qwen2.5-VL-7B-Instruct-FP8";
        const tempBotId = Date.now() + 1;
        setHistory((prev) => ([
          ...prev,
          { id: tempBotId, id_user: currentUserId, mess: "", role: "bot", session: session[0], title: "Đang tạo hợp đồng..." }
        ]));
        setShowWelcome(false);

        const handleSSEEvent = async (ev) => {
          if (ev.title && !ev.end) {
            setHistory((prev) => prev.map((m) =>
              m.id === tempBotId ? { ...m, title: ev.title } : m
            ));
          }
          if (ev.mess) {
            setHistory((prev) => prev.map((m) =>
              m.id === tempBotId ? { ...m, mess: (m.mess || "") + ev.mess } : m
            ));
          }
          if (ev.end) {
            if (ev.session_id && ev.session_id !== session[0]) {
              const data_ = await contractService.loadSession(currentUserId);
              setSessionList(decorateContractSessions(data_));
              const newIndex = data_.findIndex(s => (s.id || s) === ev.session_id);
              setSession([ev.session_id, newIndex]);
            }
            if (ev.download_url) {
              setHistory((prev) => prev.map((m) =>
                m.id === tempBotId ? { ...m, download_url: ev.download_url, path_name: ev.path_name } : m
              ));
            }
          }
        };

        let result;
        if (activeFlow === "templated") {
          result = await contractService.createContractTemplated(
            session[0],
            template[1],
            text,
            modelIdToPass,
            handleSSEEvent
          );
        } else if (activeFlow === "reasoning") {
          result = await contractService.createContractReasoning(
            session[0],
            text,
            modelIdToPass,
            handleSSEEvent
          );
        } else {
          result = await contractService.createContractFast(
            session[0],
            text,
            modelIdToPass,
            handleSSEEvent
          );
        }

        const data_ = await contractService.loadSession(currentUserId);
        setSessionList(decorateContractSessions(data_));
        const targetSessionId = result?.session_id || session[0];
        if (session[0] === -1 && targetSessionId !== -1) {
          const newIndex = data_.findIndex(s => (s.id || s) === targetSessionId);
          setSession([targetSessionId, newIndex]);
        }

        setHistory((prev) => prev.map((m) =>
          m.id === tempBotId
            ? {
              ...m,
              title: null,
              mess: result?.summary || result?.mess || m.mess,
              download_url: result?.download_url,
              path_name: result?.path_name,
            }
            : m
        ));

        toast.dismiss();
        toast.success("Đã nhận phản hồi!");
        setIsLoading(false);
      }
    } catch (error) {
      console.error("Lỗi gửi tin nhắn:", error);
      toast.error("Có lỗi xảy ra.");
      setIsStreaming(false);
      setIsLoading(false);
    }
  };

  // handleModeChange - khi user chọn tool khác trong ChatInput
  const handleModeChange = (newMode) => {
    if (newMode === 'query' && !canRag) {
      toast.error('Bạn không có quyền truy cập chế độ Truy vấn.');
      return;
    }
    if (newMode === 'contract' && !canCreateContract) {
      toast.error('Bạn không có quyền truy cập chế độ Tạo hợp đồng.');
      return;
    }
    if (newMode !== activeMode) {
      setActiveMode(newMode);
    }
  };

  const getSessionIdFromItem = (item) => {
    return typeof item === 'object' && item !== null ? Number(item.id) : Number(item);
  };

  const refreshQuerySessions = async (preferredSessionId = null) => {
    const data_ = await loadSession();
    setSessionList(data_);

    const targetId = preferredSessionId ?? session[0];
    if (targetId && targetId > 0) {
      const nextIndex = data_.findIndex((item) => getSessionIdFromItem(item) === Number(targetId));
      if (nextIndex !== -1) {
        setSession([Number(targetId), nextIndex]);
      }
    }

    return data_;
  };

  const getCurrentSessionPaths = () => {
    const currentId = Number(session[0]);
    if (!currentId || currentId === -1) return [];
    const found = sessionList.find((item) => getSessionIdFromItem(item) === currentId);
    if (!found || typeof found !== 'object') return [];
    return Array.isArray(found.paths) ? found.paths : [];
  };

  const getContractSessionPath = () => {
    const currentId = Number(session[0]);
    if (!currentId || currentId === -1) {
      return template[0] ? [template[0]] : [];
    }
    const found = sessionList.find((item) => getSessionIdFromItem(item) === currentId);
    if (found && found.template_path) return [found.template_path];
    return template[0] ? [template[0]] : [];
  };

  const handleAttachmentUpload = async (files) => {
    return await runWithFileActionLock(async () => {
      const filesArray = Array.isArray(files) ? files : [files];
      const currentSessionId = session[0] && session[0] > 0 ? session[0] : 0;

      if (activeMode === 'query') {
        let successCount = 0;
        let lastRes = null;
        for (const rawFile of filesArray) {
          // --- Client-side validation for non-root users ---
          if (!isAdmin && rawFile.size > 10 * 1024 * 1024) {
            toast.error(`File ${rawFile.name} quá lớn (tối đa 10MB cho tài khoản của bạn)`);
            continue;
          }

          try {
            setUploadProgress({ percent: 0, fileName: rawFile.name, status: 'uploading' });
            const uploadRes = await uploadFile(rawFile, currentSessionId, (percent) => {
              setUploadProgress(prev => prev ? { ...prev, percent: Math.min(percent, 99) } : null);
            });
            successCount++;
            lastRes = uploadRes;
          } catch (err) {
            console.error("Upload error:", err);
            toast.error(`Đính kèm ${rawFile.name} thất bại: ` + (err.response?.data?.detail || err.message));
          } finally {
            setUploadProgress(null);
          }
        }

        if (successCount > 0) {
          toast.success(`Đính kèm thành công ${successCount} tệp!`);
          const nextSessionId = Number(lastRes?.session_id || lastRes?.result?.session_id || 0);
          if (nextSessionId > 0) {
            await refreshQuerySessions(nextSessionId);
            setShowWelcome(false);
          } else if (currentSessionId > 0) {
            await refreshQuerySessions(currentSessionId);
          }
          const latestFiles = await loadFile();
          setFile(latestFiles);
        }
        return;
      }

      // Mode contract
      try {
        setUploadProgress({ percent: 0, fileName: filesArray.map(f => f.name).join(', '), status: 'uploading' });
        const uploadRes = await contractService.uploadMultipleTemplates(filesArray, (percent) => {
          setUploadProgress(prev => prev ? { ...prev, percent: Math.min(percent, 99) } : null);
        });
        toast.success(`Tải lên thành công ${filesArray.length} mẫu hợp đồng!`);

        const latestFiles = await contractService.loadTemplateHome();
        setFile(latestFiles);

        // Auto pin the first one
        if (filesArray[0]) {
          const firstFileName = filesArray[0].name;
          // Search in the newly loaded files to get the correct ID
          const matched = (latestFiles || []).find(f => f.name === firstFileName);
          const fileId = matched ? matched.id : -1;

          setTemplate([firstFileName, fileId]);
          const sid = Number(session[0]);
          if (sid > 0) {
            try {
              await contractService.pinContractPath(sid, firstFileName);
              const data_ = await contractService.loadSession(userId);
              setSessionList(decorateContractSessions(data_));
            } catch (err) {
              console.error("Lỗi tự động ghim template:", err);
            }
          }
        }
      } catch (err) {
        console.error("Contract upload error:", err);
        toast.error(`Tải mẫu hợp đồng thất bại: ` + (err.response?.data?.detail || err.message));
      } finally {
        setUploadProgress(null);
      }
    });
  };

  const handleAddPathToCurrentSession = async (path) => {
    if (activeMode !== 'query') return;
    if (isFileActionLoading) {
      toast.info('Đang xử lý tệp, vui lòng chờ hoàn tất.');
      return;
    }
    const currentSessionId = Number(session[0]);
    if (!currentSessionId || currentSessionId === -1) {
      toast.error('Chưa có session hiện tại để thêm đính kèm.');
      return;
    }
    await runWithFileActionLock(async () => {
      try {
        setUploadProgress({ percent: 0, fileName: path, status: 'attaching' });
        await attachFileToSession(currentSessionId, path);
        await refreshQuerySessions(currentSessionId);
      } catch (err) {
        toast.error(err.response?.data?.detail || 'Không thể đính kèm file vào session.');
      } finally {
        setUploadProgress(null);
      }
    });
  };

  const handleRemovePathFromCurrentSession = async (attachment) => {
    if (isFileActionLoading) {
      toast.info('Đang xử lý tệp, vui lòng chờ hoàn tất.');
      return;
    }
    const currentSessionId = Number(session[0]);
    if (!currentSessionId || currentSessionId === -1) {
      if (activeMode === 'contract') setTemplate(["", -1]);
      return;
    }

    const path = typeof attachment === 'string'
      ? attachment
      : (attachment?.path || attachment?.name);
    if (!path) {
      toast.error('Không xác định được file cần gỡ.');
      return;
    }

    try {
      if (activeMode === 'query') {
        await detachFileFromSession(currentSessionId, path);
        await refreshQuerySessions(currentSessionId);
      } else {
        await contractService.unpinContractPath(currentSessionId, path);
        setTemplate(["", -1]);
        const data_ = await contractService.loadSession(userId);
        setSessionList(decorateContractSessions(data_));
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Không thể gỡ file khỏi session.');
    }
  };

  const handleRenameSubmit = async (sessionId) => {
    if (!editSessionName.trim() || editSessionName === sessionList.find(s => (s.id || s) === sessionId)?.name) {
      setEditingSessionId(null);
      return;
    }

    try {
      await svc.renameSession(sessionId, editSessionName);
      setEditingSessionId(null);
      const data_ = await svc.loadSession();
      setSessionList(activeMode === 'contract' ? decorateContractSessions(data_) : data_);
      toast.success("Đổi tên thành công!");
    } catch (err) {
      toast.error("Không thể đổi tên.");
    }
  };


  const handleUpdateProfile = async () => {
    if (newPassword && newPassword !== confirmPassword) {
      toast.error("Mật khẩu xác nhận không khớp!");
      return;
    }

    setIsLoading(true);
    try {
      const updateData = {
        name: userName,
        phone: userPhone,
        address: userAddress,
      };
      if (newPassword) {
        updateData.password = newPassword;
      }

      await updateProfile(updateData);

      toast.success("Cập nhật hồ sơ thành công!");
      setIsSettingsModalOpen(false);
      setIsQuickEditSettingsOpen(false);

      // Reset password fields
      setNewPassword('');
      setConfirmPassword('');

      // Refresh local data
      localStorage.setItem('userName', userName);
      localStorage.setItem('userPhone', userPhone);
      localStorage.setItem('userAddress', userAddress);

    } catch (err) {
      console.error("Lỗi cập nhật profile:", err);
      toast.error(err.response?.data?.detail || "Không thể cập nhật hồ sơ.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleTogglePinSession = async (sessionId, isCurrentlyPinned) => {
    try {
      if (activeMode === 'query') {
        if (isCurrentlyPinned) {
          await unpinSession(sessionId);
        } else {
          await pinSession(sessionId);
        }
        const data_ = await loadSession();
        setSessionList(data_);
      } else {
        const idNum = Number(sessionId);
        const nextPinnedIds = isCurrentlyPinned
          ? contractPinnedIds.filter((id) => id !== idNum)
          : [...new Set([...contractPinnedIds, idNum])];
        setContractPinnedIds(nextPinnedIds);

        // Cần truyền nextPinnedIds vào decorateContractSessions để phản ánh UI lập tức
        setSessionList((prev) => {
          return prev.map(item => {
            const id = typeof item === 'object' && item !== null ? item.id : item;
            return {
              ...item,
              is_pinned: nextPinnedIds.includes(Number(id)),
            };
          });
        });
      }
      toast.success(isCurrentlyPinned ? "Đã bỏ ghim hội thoại" : "Đã ghim hội thoại");
    } catch (err) {
      console.error("Lỗi ghim/bỏ ghim session:", err);
      toast.error(err.response?.data?.detail || "Không thể cập nhật trạng thái ghim");
    }
  };

  const handleAvatarSelect = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setIsAvatarUploading(true);
    try {
      await uploadAvatar(file);
      const nextUrl = `${getAvatarUrl(userId)}?t=${Date.now()}`;
      setAvatarUrl(nextUrl);
      toast.success("Cập nhật avatar thành công!");
    } catch (err) {
      console.error("Lỗi upload avatar:", err);
      toast.error(err.response?.data?.detail || "Không thể cập nhật avatar.");
    } finally {
      setIsAvatarUploading(false);
      if (avatarInputRef.current) {
        avatarInputRef.current.value = '';
      }
    }
  };

  // Helper: lấy hàm service phù hợp theo mode
  const svc = activeMode === "query"
    ? { loadSession, loadHistory, deleteSession, uploadFile: uploadFile, loadFile, renameSession, pinSession, unpinSession, deleteFile }
    : { loadSession: contractService.loadSession, loadHistory: contractService.loadHistory, deleteSession: contractService.deleteSession, uploadFile: contractService.uploadMultipleTemplates, loadFile: contractService.loadTemplateHome, renameSession: contractService.renameSession, deleteTemplate: contractService.deleteTemplate };

  if (!isMounted) {
    return null; // Tránh Hydration Mismatch do Extension tiêm DOM vào khi chưa load xong JS
  }

  return (
    <div className={styles.container}>
      {/* Overlay for mobile sidebar */}
      <div 
        className={`${styles.overlay} ${isSidebarOpen ? styles.active : ''}`} 
        onClick={toggleSidebar}
      ></div>
      {/* Nút thu/mở sidebar khi sidebar đóng (nằm nổi ở góc) */}
      {!isSidebarOpen && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            zIndex: (isSettingsModalOpen || isFileManagerOpen || isWebSourcePanelOpen || isContractManagerOpen || isHelpPopupOpen || isAdminPanelOpen) ? 3000 : 9999,
            padding: '12px 10px',
            height: '60px',
            boxSizing: 'border-box',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onMouseEnter={() => setIsHoveringToggle(true)}
          onMouseLeave={() => setIsHoveringToggle(false)}
        >
          <button
            onClick={toggleSidebar}
            title="Mở sidebar"
            style={{
              position: 'relative',
              width: 40,
              height: 40,
              border: 'none',
              cursor: 'pointer',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              transition: 'background 0.2s',
              padding: 0,
              color: 'var(--text-main, #222)',
              background: 'var(--bg-sidebar)',
            }}
            aria-label="Mở rộng sidebar"
          >
            {/* Logo - ẩn khi hover */}
            <img
              src="/snowflake.png"
              alt="Logo"
              style={{
                width: 36,
                height: 36,
                objectFit: 'contain',
                position: 'absolute',
                inset: 0,
                opacity: isHoveringToggle ? 0 : 1,
                transition: 'opacity 0.15s',
                pointerEvents: 'none',
                backgroundColor: 'transparent',
                border: 'none',

              }}
            />
            {/* Icon toggle - hiện khi hover */}
            <svg
              stroke="currentColor"
              fill="none"
              strokeWidth="2"
              viewBox="0 0 24 24"
              strokeLinecap="round"
              strokeLinejoin="round"
              height="24"
              width="24"
              style={{
                position: 'relative',
                zIndex: 1,
                opacity: isHoveringToggle ? 1 : 0,
                transition: 'opacity 0.15s',
                backgroundColor: 'transparent',
              }}
            >
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="9" y1="3" x2="9" y2="21"></line>
            </svg>
          </button>
        </div>
      )}

      {/* SIDEBAR */}
      <aside 
        className={`${styles.sidebar} ${isSidebarOpen ? styles.active : styles.closed}`}
        style={typeof window !== 'undefined' && window.innerWidth <= 768 && isSidebarOpen ? { left: 0, zIndex: 3000 } : {}}
      >
        {/* Header của Sidebar: Chứa Logo và nút đóng */}
        <div
          style={{
            padding: '12px 10px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: isSidebarOpen ? 'space-between' : 'center',
            height: '60px',
            overflow: 'hidden'
          }}
        >
          {/* Logo và Text - Chỉ hiện khi Sidebar OPEN để tránh trùng lặp với logo toggle */}
          {isSidebarOpen && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <img
                src="/snowflake.png"
                alt="Logo"
                style={{
                  width: 36,
                  height: 36,
                  objectFit: 'contain',
                  flexShrink: 0
                }}
              />
              <span style={{
                fontFamily: 'var(--font-main)',
                fontWeight: 700,
                fontSize: '1.2rem',
                color: 'var(--text-main)',
                letterSpacing: '-0.02em',
                whiteSpace: 'nowrap'
              }}>
                NTC AI Assistant
              </span>
            </div>
          )}

          {/* Nút đóng sidebar (chỉ hiện khi sidebar mở) nằm bên phải */}
          {isSidebarOpen && (
            <button
              onClick={toggleSidebar}
              title="Đóng sidebar"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-main, #222)',
                padding: '8px',
                cursor: 'pointer',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'background 0.2s',
              }}
              onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(0,0,0,0.05)'}
              onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
              aria-label="Thu gọn sidebar"
            >
              <svg stroke="currentColor" fill="none" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" height="24" width="24" xmlns="http://www.w3.org/2000/svg">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <line x1="9" y1="3" x2="9" y2="21"></line>
              </svg>
            </button>
          )}
        </div>

        {/* Nội dung Sidebar */}
        <div
          ref={sidebarContentRef}
          style={{ flex: 1, overflowY: isSidebarOpen ? 'auto' : 'hidden', overflowX: 'hidden', position: 'relative' }}
        >

          {/* Nút Tạo New Chat (Chỉ hiện text khi Open) */}
          <div
            className={`${styles.newChatBtn} ${isSidebarOpen ? styles.newChatBtnExpanded : styles.newChatBtnCollapsed} ${!isSidebarOpen ? styles.sidebarCentered : ''}`}
            onClick={async () => {
              closeAllOverlays({ closeAdmin: true });
              if (!isSidebarOpen) setIsSidebarOpen(true);
              setShowWelcome(true);
              setSession([-1, -1]);
              setHistory([]);
              setIsLoading(false);
              const data_ = await svc.loadSession();
              setSessionList(activeMode === 'contract' ? decorateContractSessions(data_) : data_);
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ flexShrink: 0 }}
            >
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"></path>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
            {isSidebarOpen && (
              <span className={styles.newChatText}>
                Cuộc trò chuyện mới
              </span>
            )}
          </div>

          {/* SECTION: FILE ĐÃ TẢI LÊN (Chuyển thành nút Folder Mở Modal) */}
          {(canRag || canUpload) && (
            <div
              className={`${styles.sectionTitle} ${!isSidebarOpen ? styles.sidebarCentered : ''}`}
              onClick={() => {
                if (isFileActionLoading) {
                  toast.info('Đang xử lý tệp, vui lòng chờ hoàn tất.');
                  return;
                }
                if (!isSidebarOpen) setIsSidebarOpen(true);
                openFileManagerOverlay();
              }}
              style={{
                padding: isSidebarOpen ? '12px 16px' : '12px 0',
                justifyContent: isSidebarOpen ? 'flex-start' : 'center',
                display: 'flex',
                paddingLeft: isSidebarOpen ? '16px' : '0',
                alignItems: 'center',
                gap: '12px',
                cursor: isFileActionLoading ? 'not-allowed' : 'pointer',
                opacity: isFileActionLoading ? 0.6 : 1
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>

              {isSidebarOpen && (
                <span style={{ fontWeight: 700 }}>
                  {activeMode === "query" ? "Thư mục File" : "Mẫu hợp đồng"} ({file.length})
                </span>
              )}
            </div>
          )}

          {activeMode === "query" && canUpload && (
            <div
              className={`${styles.sectionTitle} ${!isSidebarOpen ? styles.sidebarCentered : ''}`}
              onClick={() => {
                if (!isSidebarOpen) setIsSidebarOpen(true);
                openWebSourceOverlay();
              }}
              style={{
                marginTop: 12,
                padding: isSidebarOpen ? '12px 16px' : '10px 0',
                justifyContent: isSidebarOpen ? 'flex-start' : 'center',
                display: 'flex',
                paddingLeft: isSidebarOpen ? '16px' : '0',
                alignItems: 'center',
                gap: '12px',
                cursor: 'pointer',
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
              </svg>
              {isSidebarOpen && (
                <span style={{ fontWeight: 700 }}>
                  Quản lý Nguồn Web
                </span>
              )}
            </div>
          )}

          {/* SECTION: HỢP ĐỒNG ĐÃ TẠO (Chỉ hiển thị ở chế độ Contract) */}
          {activeMode === "contract" && (canCreateContract) && (
            <div
              className={styles.sectionTitle}
              onClick={() => {
                if (!isSidebarOpen) setIsSidebarOpen(true);
                contractService.loadContract()
                  .then(data_ => setContractList(data_ || []))
                  .catch(err => console.error(err));
                openContractManagerOverlay();
              }}
              style={{
                marginTop: 12,
                padding: isSidebarOpen ? '12px 16px' : '12px 0',
                justifyContent: isSidebarOpen ? 'flex-start' : 'center',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                cursor: 'pointer'
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16h16V8l-6-6z" />
                <path d="M14 2v6h6" />
                <path d="M16 13H8" />
                <path d="M16 17H8" />
                <path d="M10 9H8" />
              </svg>
              {isSidebarOpen && (
                <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  Hợp đồng đã tạo ({contractList.length})
                </span>
              )}
            </div>
          )}

          {/* SECTION: SESSION/LỊCH SỬ CHAT */}
          <div
            className={`${styles.sectionTitle} ${!isSidebarOpen ? styles.sidebarCentered : ''}`}
            onClick={() => {
              if (!isSidebarOpen) setIsSidebarOpen(true);
              setIsSessionSectionOpen(!isSessionSectionOpen);
            }}
            style={{ 
              marginTop: 12, 
              padding: isSidebarOpen ? '12px 16px' : '12px 0', 
              justifyContent: isSidebarOpen ? 'space-between' : 'center',
              display: 'flex',
              paddingLeft: isSidebarOpen ? '16px' : '0'
            }}
          >
            {isSidebarOpen ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontWeight: 600 }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                  <span style={{ fontWeight: 700 }}>Lịch sử chat:</span>
                </div>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: isSessionSectionOpen ? 'rotate(0deg)' : 'rotate(-90deg)', transition: '0.2s' }}><path d="M6 9l6 6 6-6"></path></svg>
              </>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
            )}
          </div>

          <div className={`${styles.sectionContent} ${!isSessionSectionOpen && isSidebarOpen ? styles.collapsed : ''}`}>
            {sessionList.map((item, index) => {
              const sessionId = typeof item === 'object' && item !== null ? item.id : item;
              const sessionName = typeof item === 'object' && item !== null ? item.name || `${item.id}` : item;
              const isPinned = Boolean(typeof item === 'object' && item !== null && item.is_pinned);

              return (
                <div
                  key={index}
                  title={sessionName}
                  className={`${styles.templateItem2} ${session[1] === index ? styles.templateItem2__active : ''}`}
                >
                  {isSidebarOpen && (
                    <>
                      {editingSessionId === sessionId ? (
                        <input
                          autoFocus
                          value={editSessionName}
                          onChange={(e) => setEditSessionName(e.target.value)}
                          onBlur={() => handleRenameSubmit(sessionId)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleRenameSubmit(sessionId);
                            if (e.key === 'Escape') setEditingSessionId(null);
                          }}
                          style={{
                            flex: 1, minWidth: 0, fontSize: '0.9rem', color: 'var(--text-main)',
                            background: '#fff', border: '1px solid #ccc', borderRadius: '4px', padding: '2px 6px',
                            marginRight: '8px', zIndex: 10
                          }}
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <span
                          style={{
                            flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer', fontSize: '0.93rem', fontWeight: session[1] === index ? 700 : 400
                          }}
                          onClick={async () => {
                            closeAllOverlays({ closeAdmin: true });
                            if (!isSidebarOpen) setIsSidebarOpen(true);
                            if (activeMode === 'contract') setTemplate(["", -1]);
                            setSession([sessionId, index]);
                            setIsLoading(true);
                            const data = await svc.loadHistory(sessionId);
                            setHistory(data);
                            setIsLoading(false);
                            setShowWelcome(false);
                          }}
                        >{isPinned ? `📌 ${sessionName}` : sessionName}</span>
                      )}

                      <button
                        className={styles.menuBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          const rect = e.currentTarget.getBoundingClientRect();
                          setMenuPosition({ top: rect.bottom, left: rect.left });
                          setActiveMenu(activeMenu?.type === 'session' && activeMenu?.index === index ? null : { type: 'session', index });
                        }}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="1.5"></circle><circle cx="12" cy="5" r="1.5"></circle><circle cx="12" cy="19" r="1.5"></circle></svg>
                      </button>

                      {activeMenu?.type === 'session' && activeMenu?.index === index && (
                        <div className={styles.dropdownMenu} style={{ position: 'fixed', top: menuPosition.top, left: menuPosition.left, marginTop: 4 }}>
                          <div
                            className={styles.menuItem}
                            onClick={async () => {
                              setActiveMenu(null);
                              await handleTogglePinSession(sessionId, isPinned);
                            }}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 10V8a2 2 0 0 0-2-2h-5l-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h6"></path><path d="m15 18 3 3 6-6"></path></svg>
                            {isPinned ? 'Bỏ ghim' : 'Ghim'}
                          </div>
                          <div className={styles.menuItem} onClick={(e) => {
                            e.stopPropagation();
                            setEditingSessionId(sessionId);
                            setEditSessionName(sessionName);
                            setActiveMenu(null);
                          }}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                            Đổi tên
                          </div>
                          <div className={`${styles.menuItem} ${styles.delete}`} onClick={(e) => {
                            e.stopPropagation();
                            setActiveMenu(null);
                            svc.deleteSession(sessionId)
                              .then(() => svc.loadSession())
                              .then((data_) => {
                                if (sessionId === session[0]) {
                                  setSession([-1, -1]);
                                  setHistory([]);
                                }
                                setSessionList(activeMode === 'contract' ? decorateContractSessions(data_) : data_);
                              })
                              .catch((err) => {
                                toast.error(err.response?.data?.detail || 'Không thể xóa hội thoại.');
                              });
                          }}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                            Xóa
                          </div>
                        </div>
                      )}
                    </>
                  )
                  }
                </div>
              )
            })}
          </div>
        </div>

        {/* Profile ở dưới cùng */}
        <div
          ref={sidebarProfileRef}
          className={`${styles.userProfile} ${hasSidebarScroll ? styles.userProfileBorder : ''} ${!isSidebarOpen ? styles.sidebarCentered : ''}`}
          style={{
            justifyContent: isSidebarOpen ? 'flex-start' : 'center',
            position: 'relative',
            paddingLeft: isSidebarOpen ? '16px' : '0',
          }}
          onClick={() => {
            const opening = !isSidebarProfileOpen;
            if (opening) {
              closeAllOverlays();
              setIsSidebarProfileOpen(true);
              return;
            }
            setIsSidebarProfileOpen(false);
          }}
        >
          <div className={styles.avatarCircle}>
            {avatarUrl ? (
              <img src={avatarUrl} alt="Avatar" className={styles.avatarImage} />
            ) : (
              getInitials(userName).charAt(0)
            )}
          </div>
          {isSidebarOpen && (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{userName}</span>
              <span style={{ fontSize: '0.7rem', color: '#8e8ea0' }}>{isAdmin ? 'Admin' : 'User'}</span>
            </div>
          )}

          {isSidebarProfileOpen && (
            <div className={styles.sidebarProfileDropdown} onClick={(e) => e.stopPropagation()}>
              <div className={styles.profileMenuItem} onClick={() => {
                openSettingsOverlay();
                setIsSidebarProfileOpen(false);
              }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3"></circle>
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                </svg>
                <span>Cài đặt</span>
              </div>

              {isAdmin && (
                <div className={styles.profileMenuItem} onClick={() => {
                  openAdminOverlay('users');
                  setIsSidebarProfileOpen(false);
                }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <circle cx="12" cy="10" r="3"></circle>
                    <path d="M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662"></path>
                  </svg>
                  <span>Bảng quản trị</span>
                </div>
              )}

              <div className={styles.profileMenuItem} onClick={() => {
                openHelpOverlay();
                setIsSidebarProfileOpen(false);
              }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"></circle>
                  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                  <line x1="12" y1="17" x2="12.01" y2="17"></line>
                </svg>
                <span>Trợ giúp</span>
              </div>
              {!isAdmin && (
                <div className={styles.profileMenuItem} onClick={() => {
                  openAdminOverlay('analytics');
                  setIsSidebarProfileOpen(false);
                }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path>
                  </svg>
                  <span>Thống kê cá nhân</span>
                </div>
              )}
              <div className={styles.profileDivider}></div>
              <div className={`${styles.profileMenuItem} ${styles.signOut}`} onClick={async () => {
                try { await logoutApi(); } catch (e) { /* ignore */ }
                localStorage.removeItem('userName');
                localStorage.removeItem('userId');
                localStorage.removeItem('userEmail');
                localStorage.removeItem('userRoles');
                router.push('/signin');
              }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                  <polyline points="16 17 21 12 16 7"></polyline>
                  <line x1="21" y1="12" x2="9" y2="12"></line>
                </svg>
                <span>Đăng xuất</span>
              </div>
            </div>
          )}
        </div>
      </aside >

      {/* MAIN CONTENT AREA: CHAT OR ADMIN */}
      <main className={styles.mainChat} style={{ position: 'relative', display: 'flex', flexDirection: 'column' }}>
        {isAdmin && <NotificationListener onAlert={handleSecurityAlert} />}
        {
          isAdminPanelOpen ? (
            /* ADMIN PANEL INTEGRATED */
            <div className={styles.adminPanelIntegrated} >
              <div className={styles.adminTopNav}>
                <div className={styles.adminNavTabs}>
                  {(isAdmin ? ['users', 'analytics', 'security', 'mail', 'telegram', 'prompts', 'settings'] : []).map((tab) => (
                    <div
                      key={tab}
                      className={`${styles.adminTabItem} ${activeAdminTab === tab ? styles.adminTabActive : ''}`}
                      onClick={() => setActiveAdminTab(tab)}
                    >
                      {tab === 'users' ? 'Người dùng' :
                        tab === 'analytics' ? 'Analytics' :
                          tab === 'security' ? 'Bảo mật' :
                            tab === 'mail' ? 'Cấu hình Mail' :
                              tab === 'telegram' ? 'Quản lý Tele' :
                                tab === 'prompts' ? 'Quản lý Prompts' : 'Cài đặt'}
                    </div>
                  ))}
                </div>
                <button className={styles.closeAdminBtn} onClick={() => setIsAdminPanelOpen(false)} title="Quay lại Chat">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6L6 18"></path><path d="M6 6l12 12"></path></svg>
                </button>
              </div>

              <div className={styles.adminDataSection}>
                {activeAdminTab === 'users' && (
                  <>
                    <div className={styles.adminDataHeader}>
                      <h2>Bảng quản trị người dùng</h2>
                    </div>
                    <div className={styles.tableWrapper}>
                      <table className={styles.adminTable}>
                        <thead>
                          <tr>
                            <th style={{ textAlign: 'left', padding: '12px', width: '18%' }}>Người dùng</th>
                            <th style={{ textAlign: 'left', padding: '12px', width: '22%' }}>Email</th>
                            <th style={{ textAlign: 'center', padding: '12px', width: '10%' }}>Vai trò</th>
                            <th style={{ textAlign: 'center', padding: '12px', width: '16%' }}>Hành động</th>
                            <th style={{ textAlign: 'center', padding: '12px', width: '14%' }}>Trạng thái</th>
                            <th style={{ textAlign: 'center', padding: '12px', width: '20%' }}>Hoạt động</th>
                          </tr>
                        </thead>
                        <tbody>
                          {accountsList.length === 0 ? (
                            <tr><td colSpan="6" style={{ textAlign: 'center', padding: 32 }}>Đang tải...</td></tr>
                          ) : accountsList.map((acc) => {
                            const lastSeenDetails = getLastSeenDetails(acc);
                            return (
                              <tr key={acc.id}>
                                <td>
                                  <div className={styles.tableUserInfo} onClick={() => viewLoginHistory(acc)} style={{ cursor: 'pointer' }}>
                                    <div className={styles.tableAvatar}>{(acc.name || 'U').charAt(0).toUpperCase()}</div>
                                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                                      <span style={{ fontWeight: 600 }}>{acc.name || 'N/A'}</span>
                                      <span style={{ fontSize: '0.7rem', color: '#666' }}>ID: {acc.id}</span>
                                    </div>
                                  </div>
                                </td>
                                <td style={{ padding: '12px' }}>{acc.email}</td>
                                 <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <div
                                    className={styles.roleCell}
                                    onClick={() => {
                                      setSelectedUserForRole(acc);
                                      closeAllOverlays();
                                      setIsRoleModalOpen(true);
                                    }}
                                    style={{ cursor: 'pointer', display: 'inline-flex' }}
                                  >
                                    <div className={styles.rolePrimaryBadge}>
                                      {(() => {
                                        const primary = getHighestRole(acc.roles || []);
                                        const hasMore = acc.roles?.length > 1;
                                        return (
                                          <span className={`${styles.badge} ${styles['badge-' + primary]}`} style={{ padding: '2px 6px', borderRadius: 4, fontSize: '0.9rem' }}>
                                            {primary}{hasMore ? ' ...' : ''}
                                          </span>
                                        );
                                      })()}
                                      <div className={styles.editRoleIcon} style={{ opacity: 0.6, fontSize: '0.8rem', marginLeft: 4 }}>
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                                      </div>
                                    </div>

                                    {acc.roles && acc.roles.length > 0 && (
                                      <div className={`${styles.roleTooltip} ${styles.tooltipSideRight}`} role="tooltip">
                                        <div style={{ fontWeight: 600, marginBottom: 8, fontSize: '0.75rem', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: 4 }}>
                                          Tất cả vai trò ({acc.roles.length})
                                        </div>
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                          {acc.roles.map(r => (
                                            <span key={r} className={`${styles.badge} ${styles['badge-' + r]}`} style={{ padding: '2px 6px', borderRadius: 4, fontSize: '0.7rem' }}>
                                              {r}
                                            </span>
                                          ))}
                                        </div>
                                        <div style={{ marginTop: 8, fontSize: '0.65rem', color: '#fbbf24', textAlign: 'center' }}>
                                          Click để quản lý
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: 'center' }}>
                                    {acc.is_active ? (
                                      <button
                                        onClick={() => handleToggleActive(acc)}
                                        style={{ padding: '4px 8px', background: '#ef4444', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: '0.75rem' }}
                                        title="Khóa người dùng"
                                      >
                                        Khóa
                                      </button>
                                    ) : (
                                      <button
                                        onClick={() => handleToggleActive(acc)}
                                        style={{ padding: '4px 8px', background: '#10b981', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: '0.75rem' }}
                                        title="Mở khóa người dùng"
                                      >
                                        Mở khóa
                                      </button>
                                    )}
                                    <button
                                      onClick={() => handleDeleteAccount(acc)}
                                      style={{ padding: '4px 8px', background: '#475569', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: '0.75rem' }}
                                      title="Xóa tài khoản vĩnh viễn"
                                    >
                                      Xóa
                                    </button>
                                  </div>
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <div style={{ display: 'inline-flex', alignItems: 'center' }}>
                                    <div className={acc.is_online ? styles.onlineStatus : styles.offlineStatus} title={acc.is_online ? "Đang trực tuyến" : "Ngoại tuyến"}></div>
                                    <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{acc.is_online ? "Trực tuyến" : "Ngoại tuyến"}</span>
                                  </div>
                                </td>
                                <td style={{ padding: '12px', textAlign: 'center' }}>
                                  <span className={styles.lastSeenCell} onClick={() => viewLoginHistory(acc)} style={{ cursor: 'pointer', display: 'inline-flex' }}>
                                    <span className={styles.lastSeenText}>
                                      {acc.last_seen_at ? (acc.last_seen_action === "logout" ? "Đã đăng xuất " : "Đã đăng nhập ") : "Chưa truy cập"}
                                      {acc.last_seen_at && formatRelativeTime(acc.last_seen_at)}
                                    </span>
                                    {lastSeenDetails.length > 0 && (
                                      <span className={`${styles.lastSeenTooltip} ${styles.tooltipSideLeft}`} role="tooltip">
                                        {lastSeenDetails.map((line, idx) => (
                                          <span key={idx} className={styles.lastSeenTooltipLine}>{line}</span>
                                        ))}
                                        <span className={styles.lastSeenTooltipLine} style={{ marginTop: 4, color: '#fbbf24' }}>Click để xem lịch sử</span>
                                      </span>
                                    )}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}


                {activeAdminTab === 'analytics' && (
                  <div className={styles.analyticsContainer}>
                    <div className={styles.adminDataHeader}>
                      <h2>{isAdmin ? 'System Analytics' : 'Thống kê Cá nhân'}</h2>
                  
                    </div>
                    <div className={styles.analyticsStatsGrid}>
                      <div className={styles.statCard}>
                        <span className={styles.statNum}>{isAdmin ? analyticsData.messages : analyticsData.my_messages}</span>
                        <span className={styles.statLabel}>Tin nhắn</span>
                      </div>
                      <div className={styles.statCard}>
                        <span className={styles.statNum}>{isAdmin ? Math.round(analyticsData.tokens / 1000) + 'K' : Math.round(analyticsData.my_tokens / 1000) + 'K'}</span>
                        <span className={styles.statLabel}>Tokens tiêu thụ</span>
                      </div>
                      <div className={styles.statCard}>
                        <span className={styles.statNum}>{isAdmin ? analyticsData.chats : analyticsData.my_chats}</span>
                        <span className={styles.statLabel}>Cuộc hội thoại</span>
                      </div>
                      <div className={styles.statCard}>
                        <span className={styles.statNum}>{isAdmin ? analyticsData.users : analyticsData.my_files}</span>
                        <span className={styles.statLabel}>{isAdmin ? 'Người dùng' : 'Tài liệu'}</span>
                      </div>
                    </div>

                    {isAdmin && (
                      <div className={styles.chartSection} style={{ marginTop: '30px', padding: '0', background: 'transparent', border: 'none' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
                          <h3 style={{ margin: 0 }}>Tài nguyên Hệ thống Real-time (Native)</h3>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: '#10b981' }}>
                            <span style={{ width: '8px', height: '8px', background: '#10b981', borderRadius: '50%', display: 'inline-block', animation: 'pulse 2s infinite' }}></span>
                            Cập nhật mỗi 5s
                          </div>
                        </div>
                        
                        {!systemMetrics ? (
                          <div style={{ padding: '40px', textAlign: 'center', background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px dashed var(--border-color)' }}>
                             Đang kết nối tới Prometheus...
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                            
                            {/* Row 1: System Core & Basic Resources */}
                            <div className={styles.gaugeGrid}>
                               {/* Panel: Service Status */}
                               <div className={styles.metricPanel} style={{ flex: '2', minWidth: '350px' }}>
                                 <h4 className={styles.metricTitle}>
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M4.93 19.07L19.07 4.93"></path></svg>
                                   Trạng thái Dịch vụ
                                 </h4>
                                 <div className={styles.statusGrid}>
                                   {Object.entries(systemMetrics.core_services || {}).map(([job, status]) => (
                                     <div key={job} className={styles.statusItem} style={{ border: `1px solid ${status === 1 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}` }}>
                                       <div className={styles.statusIndicator} style={{ background: status === 1 ? '#10b981' : '#ef4444' }}></div>
                                       <span className={styles.statusLabel}>{job.replace('fastapi-', '')}</span>
                                     </div>
                                   ))}
                                 </div>
                               </div>

                               {/* Circular Gauges */}
                               {[
                                 { label: 'CPU', val: systemMetrics.cpu_usage, color: '#3b82f6' },
                                 { label: 'RAM', val: systemMetrics.ram_usage, color: '#8b5cf6' },
                                 { label: 'DISK', val: systemMetrics.disk_used, color: '#f59e0b' }
                               ].map(item => (
                                 <div key={item.label} className={`${styles.metricPanel} ${styles.gaugeCard}`}>
                                   <div style={{ position: 'relative', width: '80px', height: '80px' }}>
                                     <svg width="80" height="80" viewBox="0 0 100 100">
                                       <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="8" />
                                       <circle cx="50" cy="50" r="40" fill="none" stroke={item.color} strokeWidth="8" strokeDasharray={`${item.val * 2.51}, 251`} strokeLinecap="round" transform="rotate(-90 50 50)" style={{ transition: 'stroke-dasharray 0.5s ease' }} />
                                     </svg>
                                     <div className={styles.gaugeValue} style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }}>{Math.round(item.val)}%</div>
                                   </div>
                                   <span className={styles.gaugeLabel}>{item.label}</span>
                                 </div>
                               ))}
                            </div>

                            {/* Row 2: GPU & Performance */}
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '24px' }}>
                               {/* GPU Metrics Panel */}
                               <div className={styles.metricPanel}>
                                 <h4 className={styles.metricTitle}>
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>
                                   GPU & vRAM Analytics
                                 </h4>
                                 <div className={styles.gpuMetricGrid} style={{ gridTemplateColumns: '1fr 1fr' }}>
                                   <div className={styles.gpuMetricCard}>
                                      <div className={styles.gpuMetricInfo}>
                                        <div className={styles.gpuMetricLabel}>GPU Temp</div>
                                        <div className={styles.gpuMetricVal} style={{ color: systemMetrics.gpu_temp > 70 ? '#ef4444' : '#10b981' }}>{systemMetrics.gpu_temp}°C</div>
                                      </div>
                                      
                                   </div>
                                   <div className={styles.gpuMetricCard}>
                                      <div className={styles.gpuMetricInfo}>
                                        <div className={styles.gpuMetricLabel}>GPU Load</div>
                                        <div className={styles.gpuMetricVal}>{Math.round(systemMetrics.gpu_util)}%</div>
                                      </div>
                                      
                                   </div>
                                   <div className={styles.gpuMetricCard}>
                                      <div className={styles.gpuMetricInfo}>
                                        <div className={styles.gpuMetricLabel}>VRAM Used</div>
                                        <div className={styles.gpuMetricVal}>{Math.round(systemMetrics.vram_usage)}%</div>
                                      </div>
                                      
                                   </div>
                                   <div className={styles.gpuMetricCard}>
                                      <div className={styles.gpuMetricInfo}>
                                        <div className={styles.gpuMetricLabel}>KV Cache</div>
                                        <div className={styles.gpuMetricVal} style={{ color: systemMetrics.kv_cache > 80 ? '#f59e0b' : '#3b82f6' }}>{Math.round(systemMetrics.kv_cache)}%</div>
                                      </div>
                                      
                                   </div>
                                 </div>
                               </div>

                               {/* Token Throughput Panel */}
                               <div className={styles.metricPanel}>
                                 <h4 className={styles.metricTitle}>
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
                                   Token Throughput
                                 </h4>
                                 <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                                    <div className={styles.trafficGrid}>
                                      <div className={styles.trafficItem}>
                                        <div className={styles.trafficVal} style={{ color: '#3b82f6' }}>{Math.round(systemMetrics.token_prompt || 0)}</div>
                                        <div className={styles.trafficLabel}>Prompt/s</div>
                                      </div>
                                      <div className={styles.trafficItem}>
                                        <div className={styles.trafficVal} style={{ color: '#10b981' }}>{Math.round(systemMetrics.token_gen || 0)}</div>
                                        <div className={styles.trafficLabel}>Gen/s</div>
                                      </div>
                                    </div>
                                 </div>
                               </div>

                               {/* API Request Rate Panel */}
                               <div className={styles.metricPanel}>
                                 <h4 className={styles.metricTitle}>
                                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
                                   Lưu lượng & Hiệu năng
                                 </h4>
                                 <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                                    <div className={styles.trafficGrid}>
                                      {Object.entries(systemMetrics.api_traffic || {}).map(([job, val]) => (
                                        <div key={job} style={{ flex: 1 }}>
                                          <div className={styles.trafficVal}>{val.toFixed(2)} req/s</div>
                                          <div className={styles.trafficLabel}>{job.replace('fastapi-', '')}</div>
                                          <div style={{ height: '4px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px', marginTop: '4px' }}>
                                             <div style={{ height: '100%', width: `${Math.min(val * 10, 100)}%`, background: '#3b82f6', borderRadius: '2px' }}></div>
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                 </div>
                               </div>
                            </div>

                            {/* Row 3: Infrastructure (DBs & Storage) */}
                            <div className={styles.gaugeGrid}>
                               {[
                                 { label: 'Qdrant Vectors', val: formatNumber(systemMetrics.qdrant_vectors)},
                                 { label: 'Postgres Conns', val: systemMetrics.postgres_conns},
                                 { label: 'Redis Memory', val: formatBytes(systemMetrics.redis_mem)},
                                 { label: 'MinIO Storage', val: formatBytes(systemMetrics.minio_storage) }
                               ].map(item => (
                                 <div key={item.label} className={`${styles.metricPanel} ${styles.gpuMetricCard}`} style={{ flex: 1, minWidth: '150px', justifyContent: 'flex-start', gap: '12px' }}>
                                   <div className={styles.gpuMetricInfo}>
                                     <div className={styles.gpuMetricLabel}>{item.label}</div>
                                     <div className={styles.gpuMetricVal}>{item.val}</div>
                                   </div>
                                 </div>
                               ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {activeAdminTab === 'security' && (
                  <div className={styles.securityAlertsContainer}>
                    <div className={styles.adminDataHeader}>
                      <h2>Cảnh báo bảo mật</h2>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <button className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`} onClick={handleDeleteAllReadNotifications}>
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"></path><path d="M10 11v6M14 11v6"></path></svg>
                          Xóa đã đọc
                        </button>
                        <button className={styles.refreshBtn} onClick={fetchNotifications}>
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"></path></svg>
                          Làm mới
                        </button>
                      </div>
                    </div>
                    <div className={styles.tableWrapper}>
                      <table className={styles.adminTable}>
                        <thead>
                          <tr>
                            <th style={{ width: '140px' }}>Thời gian</th>
                            <th style={{ width: '160px' }}>Tài khoản</th>
                            <th style={{ width: '120px' }}>Loại</th>
                            <th style={{ width: '80px', textAlign: 'center' }}>Mức độ</th>
                            <th style={{ width: isSidebarOpen ? '120px' : '300px', transition: 'width 0.3s' }}>Chi tiết</th>
                            <th style={{ width: isSidebarOpen ? '100px' : '140px', transition: 'width 0.3s' }}>IP</th>
                            <th style={{ width: '180px' }}>Hành động</th>
                          </tr>
                        </thead>
                        <tbody>
                          {notifications.length === 0 ? (
                            <tr><td colSpan="7" style={{ textAlign: 'center', padding: 32, color: 'var(--text-secondary)' }}>Không có cảnh báo nào.</td></tr>
                          ) : notifications.map((n) => (
                            <tr key={n.id} style={{ opacity: n.is_read ? 0.6 : 1 }}>
                              <td style={{ fontSize: '0.8rem' }}>{new Date(n.created_at).toLocaleString('vi-VN')}</td>
                              <td>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 120 }}>
                                  {n.has_avatar ? (
                                    <img
                                      src={`${getAvatarUrl(n.account_id)}?t=${n.account_id}`}
                                      alt=""
                                      style={{ width: 28, height: 28, borderRadius: '50%', objectFit: 'cover', flexShrink: 0, border: '1px solid var(--border-color)' }}
                                      onError={(e) => { e.currentTarget.style.display = 'none'; e.currentTarget.nextSibling.style.display = 'flex'; }}
                                    />
                                  ) : null}
                                  <div
                                    style={{
                                      width: 28, height: 28, borderRadius: '50%', background: 'var(--primary-color, #6366f1)',
                                      color: '#fff', fontSize: '0.7rem', fontWeight: 600,
                                      display: n.has_avatar ? 'none' : 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0
                                    }}
                                  >
                                    {(n.account_name || n.account_email || '#').charAt(0).toUpperCase()}
                                  </div>
                                  <div style={{ overflow: 'hidden' }}>
                                    <div style={{ fontWeight: 500, fontSize: '0.85rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 100 }} title={n.account_name}>
                                      {n.account_name || `ID ${n.account_id}`}
                                    </div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 100 }} title={n.account_email}>
                                      {n.account_email || ''}
                                    </div>
                                  </div>
                                </div>
                              </td>
                              <td>{n.alert_type === 'vpn_detected' ? 'Phát hiện VPN' : n.alert_type === 'impossible_travel' ? 'Di chuyển bất thường' : n.alert_type}</td>
                              <td style={{ textAlign: 'center' }}>
                                <span className={styles.adminBadge} style={{
                                  backgroundColor: n.severity === 'critical' ? '#ef4444' : n.severity === 'high' ? '#f97316' : '#eab308'
                                }}>
                                  {n.severity.toUpperCase()}
                                </span>
                              </td>
                              <td>
                                <div style={{ 
                                  maxWidth: isSidebarOpen ? 100 : 250, 
                                  overflow: 'hidden', 
                                  textOverflow: 'ellipsis', 
                                  whiteSpace: 'nowrap',
                                  transition: 'max-width 0.3s'
                                }} title={n.title}>
                                  {n.title}
                                </div>
                              </td>
                              <td>
                                <div style={{ 
                                  maxWidth: isSidebarOpen ? 80 : 140, 
                                  overflow: 'hidden', 
                                  textOverflow: 'ellipsis', 
                                  whiteSpace: 'nowrap',
                                  transition: 'max-width 0.3s'
                                }} title={`${n.ip_address} (${n.country})`}>
                                  {n.ip_address} ({n.country})
                                </div>
                              </td>
                              <td>
                                {!n.is_read && (
                                  <button className={styles.actionBtnSmall} onClick={() => handleMarkAsRead(n.id)}>Đã đọc</button>
                                )}
                                <button
                                  className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}
                                  onClick={() => handleDeactivateFromNotif(n)}
                                  title="Khóa tài khoản này"
                                >Khóa TK</button>
                                <button
                                  className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}
                                  onClick={() => handleDeleteNotification(n.id)}
                                  title="Xóa thông báo này"
                                >
                                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"></path></svg>
                                  Xóa
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {activeAdminTab === 'mail' && <MailServerManagement styles={styles} />}
                {activeAdminTab === 'telegram' && <TelegramManagement styles={styles} />}
                {activeAdminTab === 'prompts' && <PromptManagement styles={styles} />}

                {activeAdminTab === 'settings' && (
                  <div className={styles.systemSettingsContainer}>
                    <div className={styles.adminDataHeader}>
                      <h2>Settings</h2>
                    </div>
                    <div className={styles.settingsLayoutIntegrated}>
                      <div className={styles.settingsSubSidebar}>
                        {['Models'].map(item => (
                          <div
                            key={item}
                            className={item === activeAdminSettingsTab ? styles.adminSubNavItemActive : styles.adminSubNavItem}
                            onClick={() => setActiveAdminSettingsTab(item)}
                            style={{ cursor: 'pointer' }}
                          >
                            {item}
                          </div>
                        ))}
                      </div>
                      <div className={styles.settingsContentIntegrated}>
                        
                        {activeAdminSettingsTab === 'Models' && (
                          <ModelSettings 
                            styles={styles} 
                            selectedModel={selectedModel} 
                            setSelectedModel={setSelectedModel} 
                            onModelsRefresh={refreshAvailableModels} 
                          />
                        )}

                        {activeAdminSettingsTab !== 'General' && activeAdminSettingsTab !== 'Models' && (
                          <>
                            <h3>{activeAdminSettingsTab}</h3>
                            <div style={{ padding: '24px 0', color: '#666', fontSize: '0.95rem' }}>
                              Các cài đặt cho mục {activeAdminSettingsTab} đang được phát triển...
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* CHAT INTERFACE */
            <>
              {/* --- TOP NAVBAR --- */}
              <div className={styles.topNavbar}>
                {/* Sidebar Toggle for Mobile */}
                <button
                  className={styles.navbarToggleBtn}
                  onClick={toggleSidebar}
                  aria-label="Toggle Sidebar"
                >
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="9" y1="3" x2="9" y2="21"></line>
                  </svg>
                </button>

                {/* Navbar Left: Model Selector */}
                <div className={styles.navbarLeft} ref={modelRef}>
                  <div style={{ display: 'flex', alignItems: 'center' }}>
                    <button
                      className={styles.modelNameBtn}
                      onClick={() => {
                        const opening = !isModelDropdownOpen;
                        if (opening) {
                          closeAllOverlays();
                          setIsModelDropdownOpen(true);
                          return;
                        }
                        setIsModelDropdownOpen(false);
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        padding: '8px 12px',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        cursor: 'pointer',
                        color: (selectedModel) ? 'var(--text-main)' : 'var(--text-secondary)',
                        fontSize: '1rem',
                        fontWeight: 700,
                      }}
                      onMouseOver={(e) => {
                        e.currentTarget.style.background = 'var(--color-hover-navbar)';
                      }}
                      onMouseOut={(e) => {
                        e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      {selectedModelMeta
                        ? (selectedModelMeta.display_name || selectedModelMeta.model_name).replace(/(^\w|-\w)/g, clear => clear.toUpperCase())
                        : (selectedModel ? selectedModel.replace(/(^\w|-\w)/g, clear => clear.toUpperCase()) : <span className={styles.modelPlaceholder}>Chưa kết nối</span>)}
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" style={{ marginLeft: '4px', opacity: 0.7 }}>
                        <path d="M6 9l6 6 6-6"></path>
                      </svg>
                    </button>
                  </div>

                  {isModelDropdownOpen && (
                    <div className={styles.modelDropdown}>
                      <div className={styles.modelSearchContainer}>
                        <input
                          type="text"
                          className={styles.modelSearchInput}
                          placeholder="Tìm kiếm mô hình..."
                          value={modelSearchQuery}
                          onChange={(e) => setModelSearchQuery(e.target.value)}
                          autoFocus
                        />
                      </div>
                      <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
                        {(() => {
                          const filteredModels = navbarModelOptions.filter(m =>
                            m.name.toLowerCase().includes(modelSearchQuery.toLowerCase())
                          );

                          if (filteredModels.length === 0) {
                            return (
                              <div style={{ padding: '12px 16px', color: '#70757a', fontSize: '0.9rem' }}>
                                Không tìm thấy mô hình.
                              </div>
                            );
                          }

                          return filteredModels.map((m) => (
                            <div
                              key={m.id}
                              className={`${styles.modelOption} ${m.id === selectedModel ? styles.modelOptionActive : ''}`}
                              onClick={() => {
                                handleNavbarModelSwitch(m.id);
                                setModelSearchQuery('');
                              }}
                            >
                              <div className={styles.modelInfo}>
                                <span className={styles.modelName}>{m.name.replace(/(^\w|-\w)/g, clear => clear.toUpperCase())}</span>
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{m.tag}</span>
                              </div>
                            </div>
                          ));
                        })()}
                      </div>
                    </div>
                  )}

                </div>

                {/* Navbar Right: Profile Actions */}
                <div className={styles.navbarRight} ref={profileRef}>
                  <button
                    className={styles.profileToggleBtn}
                    onClick={() => {
                      const opening = !isProfileDropdownOpen;
                      if (opening) {
                        closeAllOverlays();
                        setIsProfileDropdownOpen(true);
                        return;
                      }
                      setIsProfileDropdownOpen(false);
                    }}
                  >
                    <div className={styles.avatarCircle}>
                      {avatarUrl ? (
                        <img src={avatarUrl} alt="Avatar" className={styles.avatarImage} />
                      ) : (
                        getInitials(userName).charAt(0)
                      )}
                    </div>
                  </button>

                  {isProfileDropdownOpen && (
                    <div className={styles.profileDropdown}>
                      <div className={styles.profileMenuItem} onClick={() => {
                        openSettingsOverlay();
                        setIsProfileDropdownOpen(false);
                      }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="12" cy="12" r="3"></circle>
                          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                        </svg>
                        <span>Cài đặt</span>
                      </div>
                      {isAdmin && (
                        <div className={styles.profileMenuItem} onClick={() => {
                          openAdminOverlay('users');
                          setIsProfileDropdownOpen(false);
                        }}>
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="12" cy="12" r="10"></circle>
                            <circle cx="12" cy="10" r="3"></circle>
                            <path d="M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662"></path>
                          </svg>
                          <span>Bảng quản trị</span>
                        </div>
                      )}
                      <div className={styles.profileMenuItem} onClick={() => {
                        openHelpOverlay();
                        setIsProfileDropdownOpen(false);
                      }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="12" cy="12" r="10"></circle>
                          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                          <line x1="12" y1="17" x2="12.01" y2="17"></line>
                        </svg>
                        <span>Trợ giúp</span>
                      </div>
                      

                      {!isAdmin && (
                        <div className={styles.profileMenuItem} onClick={() => {
                          openAdminOverlay('analytics');
                          setIsProfileDropdownOpen(false);
                        }}>
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path>
                          </svg>
                          <span>Thống kê cá nhân</span>
                        </div>
                      )}

                      <div className={styles.profileDivider}></div>
                      <div className={`${styles.profileMenuItem} ${styles.signOut}`} onClick={async () => {
                        try { await logoutApi(); } catch (e) { /* ignore */ }
                        localStorage.removeItem('userName');
                        localStorage.removeItem('userId');
                        localStorage.removeItem('userEmail');
                        localStorage.removeItem('userRoles');
                        router.push('/signin');
                      }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                          <polyline points="16 17 21 12 16 7"></polyline>
                          <line x1="21" y1="12" x2="9" y2="12"></line>
                        </svg>
                        <span>Đăng xuất</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
              {showWelcome && session[0] === -1 && (
                <div style={{
                  width: '100%',
                  height: '100vh',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 24
                }}>
                  <div style={{ width: '100%', maxWidth: 800, display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <img src="/snowflake.png" alt="Sparkle" style={{ width: 48, height: 48, objectFit: 'contain' }} />
                      <h2 style={{ fontWeight: 600, fontSize: '2.2rem', margin: 0, color: 'var(--text-main)' }}>Xin chào {userName}!</h2>
                    </div>
                    <h2 style={{ fontWeight: 400, fontSize: '1.8rem', margin: 0, color: 'var(--text-secondary)' }}>Hãy bắt đầu nhập câu hỏi của bạn</h2>
                  </div>
                  {/* Chat input bar */}
                  <div style={{ width: '100%', maxWidth: 800, margin: '0 auto' }}>
                    <ChatInput
                      key={session[0]}
                      activeMode={activeMode}
                      flowOption={activeFlow}
                      onFlowChange={setActiveFlow}
                      onModeChange={handleModeChange}
                      onSendMessage={handleSendMessage}
                      onUpload={handleAttachmentUpload}
                      onRemoveAttachment={handleRemovePathFromCurrentSession}
                      attachments={activeMode === 'query' ? getCurrentSessionPaths() : getContractSessionPath()}
                      isLoading={isLoading || isFileActionLoading || isStreaming}
                      userRoles={userRoles}
                    />
                    <p style={{ textAlign: "center", fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "12px", opacity: 0.8 }}>Chatbot có thể mắc sai lầm. Hãy kiểm tra những thông tin quan trọng.</p>
                  </div>
                </div>
              )}
              {/* Chat UI như cũ */}

              <div style={showWelcome ? { display: 'none' } : { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                <div className={styles.chatScrollWrapper}>
                  <div className={styles.chatContainer} style={{ paddingBottom: 20 }}>
                    {history?.map((data, index) => {
                      if (data.role === "user") {
                        return (
                          <div key={index} className={`${styles.message} ${styles.messageUser}`}>
                            <div className={styles.messageContent}>
                              <BotMessage content={data.mess} downloadUrl={data.download_url} />
                            </div>
                          </div>
                        );
                      } else {
                        return (
                          <div key={index} style={{ width: '100%' }}>
                            <ReasoningBox
                              title={data.title}
                              sourceFiles={data.source_files}
                              showLiveStatus={
                                activeMode === 'query' &&
                                activeFlow === 'web_search' &&
                                isStreaming &&
                                index === history.length - 1
                              }
                            />
                            <div className={`${styles.message} ${styles.messageBot}`}>
                              <div style={{ width: 40, height: 40, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', flexShrink: 0 }}>
                                <img src="/snowflake.png" alt="Bot" style={{ width: 42, height: 42, objectFit: 'contain' }} />
                              </div>
                              <div className={styles.messageContent}>
                                <BotMessage content={data.mess} downloadUrl={data.download_url} />
                              </div>
                            </div>
                          </div>
                        );
                      }
                    })}
                    <div ref={messagesEndRef} />
                  </div>
                </div>

                {/* Input Area tách riêng, nằm hoàn toàn phía bên ngoài thẻ chatContainer */}
                {!showWelcome && (
                  <div style={{ padding: '0 20px 0px 20px', width: '100%', maxWidth: '800px', margin: '0 auto', flexShrink: 0 }}>
                    <ChatInput
                      key={session[0]}
                      activeMode={activeMode}
                      flowOption={activeFlow}
                      onFlowChange={setActiveFlow}
                      onModeChange={handleModeChange}
                      onSendMessage={handleSendMessage}
                      onUpload={handleAttachmentUpload}
                      onRemoveAttachment={handleRemovePathFromCurrentSession}
                      attachments={activeMode === 'query' ? getCurrentSessionPaths() : getContractSessionPath()}
                      isLoading={isLoading || isFileActionLoading || isStreaming}
                      userRoles={userRoles}
                    />
                    <p style={{ textAlign: "center", fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "12px", opacity: 0.8 }}>Chatbot có thể mắc sai lầm. Hãy kiểm tra những thông tin quan trọng.</p>
                  </div>
                )}
              </div>
            </>
          )
        }

        {/* Tiến trình đã hiển thị như message bot trong chat */}
        {/* Loading icon vẫn giữ lại nếu muốn */}
        <div className={`${styles.loading} ${isLoading ? styles.loading_acctive : ""}`}>
          <img src="/Spinner@1x-1.0s-200px-200px.gif" alt="" />
        </div>

        {/* Trợ giúp Popup */}
        {isHelpPopupOpen && (
          <div className={styles.helpPopupOverlay} onClick={() => setIsHelpPopupOpen(false)}>
            <div className={styles.helpPopup} onClick={(e) => e.stopPropagation()}>
              <div className={styles.helpPopupHeader}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--text-primary)' }}>
                    <circle cx="12" cy="12" r="10"></circle>
                    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                  </svg>
                  <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>Trợ giúp</h3>
                </div>
                <button 
                  onClick={() => setIsHelpPopupOpen(false)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2rem', color: 'var(--text-secondary)' }}
                >✕</button>
              </div>
              <div className={styles.helpPopupContent}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  {/* Accordion 1 */}
                  <div className={styles.helpAccordionItem}>
                    <div 
                      className={styles.helpAccordionHeader} 
                      onClick={() => setOpenHelpSection(openHelpSection === 'query' ? null : 'query')}
                    >
                      <span style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Hướng dẫn dùng truy vấn dữ liệu</span>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`${styles.helpAccordionIcon} ${openHelpSection === 'query' ? styles.helpAccordionIconOpen : ''}`}>
                        <polyline points="6 9 12 15 18 9"></polyline>
                      </svg>
                    </div>
                    <div className={`${styles.helpAccordionContent} ${openHelpSection === 'query' ? styles.helpAccordionContentOpen : ''}`}>
                      <div className={styles.helpAccordionInner}>
                        <div style={{ marginBottom: 12 }}>
                          <p style={{ margin: '0 0 8px 0', fontSize: '0.9rem', lineHeight: 1.6, fontWeight: 600, color: 'var(--text-primary)' }}>Cơ chế hoạt động:</p>
                          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.875rem', lineHeight: 1.6, color: 'var(--text-main)' }}>
                            <li><strong>Khi không đính kèm tệp:</strong> AI sẽ tự động truy vấn từ kho dữ liệu hệ thống hiện có.</li>
                            <li><strong>Khi đính kèm tệp:</strong> AI sẽ chỉ tập trung trả lời dựa trên nội dung tệp đã tải lên.</li>
                            <li><strong>Lưu ý:</strong> Hệ thống <strong>không hỗ trợ</strong> Web Search (truy xuất từ mạng).</li>
                          </ul>
                        </div>
                        <div>
                          <p style={{ margin: '0 0 8px 0', fontSize: '0.9rem', lineHeight: 1.6, fontWeight: 600, color: 'var(--text-primary)' }}>Quy trình sử dụng:</p>
                          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.875rem', lineHeight: 1.6, color: 'var(--text-main)' }}>
                            <li><strong>Bước 1:</strong> Tải tệp tài liệu lên qua biểu tượng đính kèm (nếu cần hỏi riêng trên tệp).</li>
                            <li><strong>Bước 2:</strong> Nhập câu hỏi liên quan vào khung chat và nhấn gửi.</li>
                            <li><strong>Bước 3:</strong> Chờ giây lát để AI phân tích và trình bày kết quả tìm kiếm được.</li>
                          </ul>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Accordion 2 */}
                  <div className={styles.helpAccordionItem}>
                    <div 
                      className={styles.helpAccordionHeader} 
                      onClick={() => setOpenHelpSection(openHelpSection === 'contract' ? null : 'contract')}
                    >
                      <span style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Hướng dẫn dùng tạo hợp đồng</span>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`${styles.helpAccordionIcon} ${openHelpSection === 'contract' ? styles.helpAccordionIconOpen : ''}`}>
                        <polyline points="6 9 12 15 18 9"></polyline>
                      </svg>
                    </div>
                    <div className={`${styles.helpAccordionContent} ${openHelpSection === 'contract' ? styles.helpAccordionContentOpen : ''}`}>
                      <div className={styles.helpAccordionInner}>
                        <div style={{ marginBottom: 12 }}>
                          <p style={{ margin: '0 0 8px 0', fontSize: '0.9rem', lineHeight: 1.6, fontWeight: 600, color: 'var(--text-primary)' }}>Các chế độ hỗ trợ:</p>
                          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.875rem', lineHeight: 1.6, color: 'var(--text-main)', display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <li><strong>Fast:</strong> Tạo nhanh hợp đồng cơ bản với ít thông tin đầu vào nhất.</li>
                            <li><strong>Reasoning:</strong> Quy trình kiểm soát và phân tích điều khoản chặt chẽ, chính xác.</li>
                            <li><strong>Templated:</strong> Tạo dựa trên mẫu có sẵn, AI sẽ hỏi bạn để điền thông tin thiếu.</li>
                          </ul>
                        </div>
                        <div>
                          <p style={{ margin: '0 0 8px 0', fontSize: '0.9rem', lineHeight: 1.6, fontWeight: 600, color: 'var(--text-primary)' }}>Quy trình thực hiện:</p>
                          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.875rem', lineHeight: 1.6, color: 'var(--text-main)' }}>
                            <li><strong>Bước 1:</strong> Chọn chế độ &quot;Tạo Hợp Đồng&quot; trong thanh công cụ bên dưới khung chat.</li>
                            <li><strong>Bước 2:</strong> Chọn phương thức (Fast, Reasoning hoặc Templated) phù hợp với nhu cầu.</li>
                            <li><strong>Bước 3:</strong> Cung cấp thông tin:
                              <ul style={{ margin: '4px 0 0 0', paddingLeft: 18, fontSize: '0.85rem', listStyleType: 'circle', display: 'flex', flexDirection: 'column', gap: 2 }}>
                                <li><strong>Fast / Reasoning:</strong> Điền các thông tin cơ bản ngay từ đầu (Fast yêu cầu ít thông tin, còn Reasoning sẽ xử lý dữ liệu cẩn trọng hơn).</li>
                                <li><strong>Templated:</strong> Điền thông tin theo bộ khung mẫu sẵn có, AI sẽ chỉ hỏi thêm nếu phát hiện mẫu còn thiếu thông tin.</li>
                              </ul>
                            </li>
                            <li><strong>Bước 4:</strong> Sau khi hoàn thành, kiểm tra lại nội dung và nhấn Tải về file PDF/Word.</li>
                          </ul>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div style={{ padding: 12, backgroundColor: 'rgba(240, 173, 78, 0.1)', borderLeft: '4px solid #f0ad4e', borderRadius: 4, marginTop: 4 }}>
                    <p style={{ fontSize: '0.85rem', margin: 0, color: 'var(--text-main)', lineHeight: 1.5 }}>
                      <strong>Lưu ý:</strong> AI có khả năng nhầm lẫn, vui lòng kiểm tra kĩ nội dung quan trọng trước khi sử dụng.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* SETTINGS MODAL */}
        {
          isSettingsModalOpen && (
            <div className={styles.settingsOverlay} onClick={() => setIsSettingsModalOpen(false)}>
              <div className={styles.settingsModal} onClick={(e) => e.stopPropagation()}>
                <div className={styles.settingsHeader}>
                  <span>Cài đặt</span>
                  <button className={styles.closeModalBtn} onClick={() => setIsSettingsModalOpen(false)}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                  </button>
                </div>

                <div className={styles.settingsBody}>
                  <div className={styles.settingsSidebar}>
                    <div className={styles.settingsSearchContainer}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                      <input type="text" placeholder="Tìm kiếm" className={styles.settingsSearchInput} />
                    </div>

                    <div
                      className={`${styles.settingsTabItem} ${activeSettingsTab === 'general' ? styles.tabActive : ''}`}
                      onClick={() => setActiveSettingsTab('general')}
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                      Chung
                    </div>

                    <div
                      className={`${styles.settingsTabItem} ${activeSettingsTab === 'account' ? styles.tabActive : ''}`}
                      onClick={() => setActiveSettingsTab('account')}
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                      Tài khoản
                    </div>
                    <div style={{ marginTop: 'auto' }}>
                      <div style={{ width: '100%', height: '2px', backgroundColor: '#e0e0e0', margin: '8px 0', borderRadius: '1px' }}></div>
                      <div
                        className={`${styles.settingsTabItem} ${activeSettingsTab === 'about' ? styles.tabActive : ''}`}
                        onClick={() => setActiveSettingsTab('about')}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                        Giới thiệu
                      </div>

                      {isAdmin && (<div
                        className={styles.settingsTabItem}
                        onClick={() => {
                          openAdminOverlay('users');
                        }}
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="10" r="3"></circle><path d="M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662"></path></svg>
                        Cài đặt quản trị
                      </div>)}
                    </div>
                  </div>

                  <div className={styles.settingsMainContent}>
                    {activeSettingsTab === 'general' && (
                      <div className={styles.settingsTabContent}>
                        <h3>Cài đặt NTC chat</h3>
                        <div className={styles.settingsRow}>
                          <div className={styles.settingsLabel}>
                            <span>Chủ đề</span>
                          </div>
                          <div className={styles.settingsValue}>
                            <select
                              className={styles.settingsSelect}
                              value={theme}
                              onChange={(e) => setTheme(e.target.value)}
                            >
                              <option value="light">Sáng</option>
                              <option value="dark">Tối</option>
                              <option value="system">Theo hệ thống</option>
                            </select>
                          </div>
                        </div>

                      </div>
                    )}

                    {activeSettingsTab === 'account' && (
                      <div className={styles.settingsTabContent}>
                        <div style={{ paddingBottom: '24px', borderBottom: '1px solid #f0f0f0', marginBottom: '24px' }}>
                          <h3 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-main)' }}>Hồ sơ cá nhân</h3>
                          <p style={{ margin: '4px 0 0 0', color: 'var(--text-sub)', fontSize: '0.9rem' }}>Quản lý thông tin tài khoản của bạn.</p>
                        </div>

                        <div className={styles.profileCard}>
                          <div
                            className={styles.avatarFrame}
                            onClick={() => setIsQuickEditSettingsOpen(!isQuickEditSettingsOpen)}
                          >
                            <div className={styles.avatarFrameInner}>
                              {avatarUrl ? (
                                <img src={avatarUrl} alt="Avatar" />
                              ) : (
                                getInitials(userName).charAt(0)
                              )}
                            </div>
                            <div className={styles.avatarBadge} title="Sửa thông tin">
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
                              </svg>
                            </div>
                          </div>

                          <div className={styles.profileInfoMini}>
                            <h3>{userName}</h3>
                            <p>{userEmail}</p>
                            <button
                              type="button"
                              style={{
                                marginTop: '12px',
                                padding: '6px 12px',
                                fontSize: '0.75rem',
                                borderRadius: '20px',
                                border: '1px solid var(--border-color)',
                                background: 'transparent',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer'
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                avatarInputRef.current?.click();
                              }}
                            >
                              {isAvatarUploading ? 'Đang tải...' : 'Đổi ảnh đại diện'}
                            </button>
                          </div>

                          <input
                            ref={avatarInputRef}
                            type="file"
                            accept="image/*"
                            onChange={handleAvatarSelect}
                            style={{ display: 'none' }}
                          />

                          {/* NEW RE-IMPLEMENTED QUICK EDIT - ISOLATED FROM GLOBAL CSS */}
                          {isQuickEditSettingsOpen && (
                            <div 
                              onClick={(e) => e.stopPropagation()}
                              style={{
                                position: 'absolute',
                                top: '135px',
                                left: '50%',
                                transform: 'translateX(-50%)',
                                width: '340px',
                                background: 'rgba(255, 255, 255, 0.95)',
                                backdropFilter: 'blur(12px)',
                                border: '1px solid rgba(226, 232, 240, 0.8)',
                                borderRadius: '20px',
                                boxShadow: '0 20px 50px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(0,0,0,0.05)',
                                padding: '28px',
                                zIndex: 10000,
                                display: 'block',
                                color: '#1e293b',
                                boxSizing: 'border-box',
                                textAlign: 'left',
                                fontFamily: 'inherit'
                              }}
                            >
                              <div style={{ marginBottom: '20px', textAlign: 'center' }}>
                                <span style={{ display: 'block', fontSize: '1.25rem', fontWeight: 700, color: '#0f172a', letterSpacing: '-0.02em' }}>Chỉnh sửa hồ sơ</span>
                                <span style={{ display: 'block', fontSize: '0.875rem', color: '#64748b', marginTop: '6px' }}>Cập nhật thông tin định danh của bạn</span>
                              </div>

                              {/* Form Field: Full Name */}
                              <div style={{ marginBottom: '18px', display: 'block' }}>
                                <span style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#475569', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em', paddingLeft: '4px' }}>Họ và tên</span>
                                <div style={{ position: 'relative', display: 'block' }}>
                                  <input
                                    type="text"
                                    style={{
                                      display: 'block',
                                      width: '100%',
                                      padding: '12px 16px',
                                      background: '#f8fafc',
                                      border: '2px solid #f1f5f9',
                                      borderRadius: '12px',
                                      color: '#1e293b',
                                      fontSize: '0.95rem',
                                      fontWeight: 500,
                                      boxSizing: 'border-box',
                                      transition: 'all 0.2s ease',
                                      outline: 'none'
                                    }}
                                    value={userName}
                                    onChange={(e) => setUserName(e.target.value)}
                                    placeholder="Nhập họ và tên..."
                                    onFocus={(e) => {
                                      e.target.style.borderColor = '#3b82f6';
                                      e.target.style.background = '#ffffff';
                                      e.target.style.boxShadow = '0 0 0 4px rgba(59, 130, 246, 0.1)';
                                    }}
                                    onBlur={(e) => {
                                      e.target.style.borderColor = '#f1f5f9';
                                      e.target.style.background = '#f8fafc';
                                      e.target.style.boxShadow = 'none';
                                    }}
                                  />
                                </div>
                              </div>

                              {/* Form Field: Phone Number */}
                              <div style={{ marginBottom: '18px', display: 'block' }}>
                                <span style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#475569', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em', paddingLeft: '4px' }}>Số điện thoại</span>
                                <div style={{ position: 'relative', display: 'block' }}>
                                  <input
                                    type="text"
                                    style={{
                                      display: 'block',
                                      width: '100%',
                                      padding: '12px 16px',
                                      background: '#f8fafc',
                                      border: '2px solid #f1f5f9',
                                      borderRadius: '12px',
                                      color: '#1e293b',
                                      fontSize: '0.95rem',
                                      fontWeight: 500,
                                      boxSizing: 'border-box',
                                      transition: 'all 0.2s ease',
                                      outline: 'none'
                                    }}
                                    value={userPhone}
                                    onChange={(e) => setUserPhone(e.target.value)}
                                    placeholder="Nhập số điện thoại..."
                                    onFocus={(e) => {
                                      e.target.style.borderColor = '#3b82f6';
                                      e.target.style.background = '#ffffff';
                                      e.target.style.boxShadow = '0 0 0 4px rgba(59, 130, 246, 0.1)';
                                    }}
                                    onBlur={(e) => {
                                      e.target.style.borderColor = '#f1f5f9';
                                      e.target.style.background = '#f8fafc';
                                      e.target.style.boxShadow = 'none';
                                    }}
                                  />
                                </div>
                              </div>

                              {/* Form Field: Address */}
                              <div style={{ marginBottom: '24px', display: 'block' }}>
                                <span style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#475569', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em', paddingLeft: '4px' }}>Địa chỉ</span>
                                <div style={{ position: 'relative', display: 'block' }}>
                                  <input
                                    type="text"
                                    style={{
                                      display: 'block',
                                      width: '100%',
                                      padding: '12px 16px',
                                      background: '#f8fafc',
                                      border: '2px solid #f1f5f9',
                                      borderRadius: '12px',
                                      color: '#1e293b',
                                      fontSize: '0.95rem',
                                      fontWeight: 500,
                                      boxSizing: 'border-box',
                                      transition: 'all 0.2s ease',
                                      outline: 'none'
                                    }}
                                    value={userAddress}
                                    onChange={(e) => setUserAddress(e.target.value)}
                                    placeholder="Nhập địa chỉ của bạn..."
                                    onFocus={(e) => {
                                      e.target.style.borderColor = '#3b82f6';
                                      e.target.style.background = '#ffffff';
                                      e.target.style.boxShadow = '0 0 0 4px rgba(59, 130, 246, 0.1)';
                                    }}
                                    onBlur={(e) => {
                                      e.target.style.borderColor = '#f1f5f9';
                                      e.target.style.background = '#f8fafc';
                                      e.target.style.boxShadow = 'none';
                                    }}
                                  />
                                </div>
                              </div>

                              {/* Action Buttons */}
                              <div style={{ display: 'flex', gap: '12px' }}>
                                <button 
                                  style={{
                                    flex: 1.5,
                                    background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
                                    color: 'white',
                                    border: 'none',
                                    padding: '14px',
                                    borderRadius: '14px',
                                    fontWeight: 700,
                                    fontSize: '0.95rem',
                                    cursor: 'pointer',
                                    boxShadow: '0 4px 12px rgba(37, 99, 235, 0.25)',
                                    transition: 'transform 0.2s ease, box-shadow 0.2s ease'
                                  }}
                                  onMouseEnter={(e) => {
                                    e.currentTarget.style.transform = 'translateY(-2px)';
                                    e.currentTarget.style.boxShadow = '0 6px 15px rgba(37, 99, 235, 0.35)';
                                  }}
                                  onMouseLeave={(e) => {
                                    e.currentTarget.style.transform = 'translateY(0)';
                                    e.currentTarget.style.boxShadow = '0 4px 12px rgba(37, 99, 235, 0.25)';
                                  }}
                                  onClick={handleUpdateProfile}
                                >
                                  Lưu thay đổi
                                </button>
                                <button 
                                  style={{
                                    flex: 1,
                                    background: '#f1f5f9',
                                    color: '#475569',
                                    border: '1px solid #e2e8f0',
                                    padding: '14px',
                                    borderRadius: '14px',
                                    fontWeight: 600,
                                    fontSize: '0.95rem',
                                    cursor: 'pointer',
                                    transition: 'background 0.2s ease'
                                  }}
                                  onMouseEnter={(e) => e.currentTarget.style.background = '#e2e8f0'}
                                  onMouseLeave={(e) => e.currentTarget.style.background = '#f1f5f9'}
                                  onClick={() => setIsQuickEditSettingsOpen(false)}
                                >
                                  Hủy
                                </button>
                              </div>
                            </div>
                          )}
                        </div>

                        <div className={styles.settingsRow} style={{ border: 'none', padding: 0 }}>
                          <div className={styles.settingsLabel}>
                            <span>Email</span>
                            <p className={styles.settingsSubLabel}>Email không thể thay đổi</p>
                          </div>
                          <div className={styles.settingsValue}>
                            <input
                              type="text"
                              className={styles.settingsSelect}
                              value={userEmail}
                              disabled
                              style={{ backgroundColor: 'var(--color-accent)', cursor: 'not-allowed' }}
                            />
                          </div>
                        </div>

                        <div style={{ marginTop: '10px', paddingTop: '20px', borderTop: '1px solid var(--border-color)' }}>
                          <h4 style={{ marginBottom: '16px', color: 'var(--text-main)' }}>Đổi mật khẩu</h4>
                          <div className={styles.settingsRow} style={{ border: 'none', padding: 0, marginBottom: '12px' }}>
                            <div className={styles.settingsLabel}>
                              <span>Mật khẩu mới</span>
                            </div>
                            <div className={styles.settingsValue}>
                              <input
                                type="password"
                                className={styles.settingsSelect}
                                value={newPassword}
                                onChange={(e) => setNewPassword(e.target.value)}
                                placeholder="Nhập mật khẩu mới"
                              />
                            </div>
                          </div>
                          <div className={styles.settingsRow} style={{ border: 'none', padding: 0 }}>
                            <div className={styles.settingsLabel}>
                              <span>Xác nhận mật khẩu</span>
                            </div>
                            <div className={styles.settingsValue}>
                              <input
                                type="password"
                                className={styles.settingsSelect}
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                placeholder="Xác nhận mật khẩu"
                              />
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Các tab khác có thể thêm nội dung tương tự */}
                    {activeSettingsTab === 'about' && (
                      <div className={styles.settingsTabContent}>
                        <div style={{ paddingBottom: '24px', borderBottom: '1px solid var(--border-color)', marginBottom: '24px' }}>
                          <h3 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-main)' }}>Về Hệ Thống</h3>
                          <p style={{ margin: '8px 0 0 0', color: 'var(--text-sub)', lineHeight: '1.6' }}>
                            Chào mừng bạn đến với hệ thống RAG Chatbot. Đây là một trợ lý thông minh giúp bạn tìm kiếm và tổng hợp thông tin từ dữ liệu nội bộ một cách nhanh chóng.
                          </p>
                        </div>

                        <div style={{ marginBottom: '24px' }}>
                          <h4 style={{ margin: '0 0 16px 0', fontSize: '1.1rem', color: 'var(--text-main)' }}>Các Chế Độ</h4>
                          
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#3b82f6' }}></div>
                                <strong style={{ color: 'var(--text-main)' }}>Truy vấn (RAG)</strong>
                              </div>
                              <p style={{ margin: 0, fontSize: '0.9rem', color: 'var(--text-sub)', paddingLeft: '18px' }}>
                                Phân tích và trả lời dựa trên tệp dữ liệu đã tải lên.
                              </p>
                            </div>

                            <div style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }}></div>
                                <strong style={{ color: 'var(--text-main)' }}>Tạo Hợp Đồng</strong>
                              </div>
                              <p style={{ margin: 0, fontSize: '0.9rem', color: 'var(--text-sub)', paddingLeft: '18px' }}>
                                Hỗ trợ soạn thảo và kiểm tra các loại hợp đồng pháp lý.
                              </p>
                            </div>
                          </div>
                        </div>

                        <div style={{ marginTop: 'auto', textAlign: 'center', opacity: 0.6, paddingTop: '20px' }}>
                          <p style={{ fontSize: '0.8rem', margin: 0 }}>Phiên bản 1.0.0 • NTC AI Solution</p>
                        </div>
                      </div>
                    )}

                    {activeSettingsTab !== 'general' && activeSettingsTab !== 'account' && activeSettingsTab !== 'about' && (
                      <div className={styles.settingsTabContentPlaceholder}>
                        <h3>{activeSettingsTab.charAt(0).toUpperCase() + activeSettingsTab.slice(1)}</h3>
                        <p>Nội dung đang được cập nhật...</p>
                      </div>
                    )}
                  </div>
                </div>

                <div className={styles.settingsFooter}>
                  <button className={styles.saveBtn} onClick={() => {
                    if (activeSettingsTab === 'account') {
                      handleUpdateProfile();
                    } else {
                      setIsSettingsModalOpen(false);
                    }
                  }}>Lưu</button>
                </div>
              </div>
            </div>
          )
        }
      </main >

      {/* FileManager Modal */}
      {isWebSourcePanelOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.45)',
            zIndex: 10010,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
          onClick={() => setIsWebSourcePanelOpen(false)}
        >
          <div
            style={{
              width: 'min(1100px, 100%)',
              maxHeight: '85vh',
              overflow: 'auto',
              background: 'var(--bg-main)',
              border: '1px solid var(--border-color)',
              borderRadius: '16px',
              boxShadow: '0 20px 50px rgba(0,0,0,0.3)',
              padding: '20px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <WebSourceManagement styles={styles} onClose={() => setIsWebSourcePanelOpen(false)} />
          </div>
        </div>
      )}

      < FileManagerModal
        isOpen={isFileManagerOpen}
        userRoles={userRoles}
        onClose={() => setIsFileManagerOpen(false)}
        activeMode={activeMode}
        files={file}
        svc={svc}
        isBusy={isFileActionLoading}
        onBusyChange={setFileActionBusy}
        currentSessionId={Number(session[0])}
        canSelect={activeFlow === 'templated' || activeMode === 'query'}
        canDelete={!userRoles.map(r => r.toLowerCase()).includes('rag') && !userRoles.map(r => r.toLowerCase()).includes('create')}
        onRefresh={async (uploadRes) => {
          if (activeMode === 'query') {
            svc.loadFile().then((data_) => setFile(data_)).catch((err) => console.error('loadFile error:', err));
            const sid = Number(uploadRes?.session_id || uploadRes?.result?.session_id || 0);
            await refreshQuerySessions(sid > 0 ? sid : null);
            if (sid > 0) {
              setShowWelcome(false);
            }
          } else {
            contractService.loadTemplateHome().then((data_) => setFile(data_)).catch((err) => console.error('loadTemplateHome error:', err));
          }
        }}
        onFileDeleted={async (deletedFile) => {
          const deletedFileName = typeof deletedFile === 'object' && deletedFile !== null ? deletedFile.name : deletedFile;
          if (activeMode === 'contract') {
            if (template[0] === deletedFileName || template[1] === deletedFile?.id) {
              setTemplate(["", -1]);
              const sid = Number(session[0]);
              if (sid > 0 && contractService.unpinContractPath) {
                try {
                  await contractService.unpinContractPath(sid, deletedFileName);
                  const data_ = await contractService.loadSession(userId);
                  setSessionList(decorateContractSessions(data_));
                } catch (err) {
                  console.error("Lỗi bỏ ghim template:", err);
                }
              }
            }
          }
        }}
        onFileSelect={async (selectedFile, idx) => {
          const fileName = typeof selectedFile === 'object' && selectedFile !== null ? selectedFile.name : selectedFile;
          const fileId = typeof selectedFile === 'object' && selectedFile !== null && selectedFile.id !== undefined
            ? selectedFile.id
            : idx;
          if (activeMode === 'query') {
            await runWithFileActionLock(async () => {
              try {
                setUploadProgress({ percent: 0, fileName, status: 'attaching' });

                let targetSessionId = Number(session[0]);
                let isNewSession = false;

                if (!(targetSessionId > 0)) {
                  // 1. Tạo session mới nếu chưa có session hiện tại
                  const res = await createSession(fileName);
                  // Backend trả về result: { id, name, ... } hoặc chỉ id
                  targetSessionId = res.result?.id || res.result;
                  isNewSession = true;
                }

                // 2. Đính kèm file vào session (mới hoặc cũ)
                await attachFileToSession(targetSessionId, fileName);

                // 3. Refresh danh sách session và chuyển sang session đó
                const data_ = await loadSession();
                setSessionList(data_);

                if (isNewSession) {
                  const newIndex = data_.findIndex(s => (s.id || s) === targetSessionId);
                  setSession([targetSessionId, newIndex]);
                  setHistory([]);
                  setShowWelcome(false);
                  toast.success(`Đã tạo phiên hỏi đáp mới cho tệp: ${fileName}`);
                } else {
                  toast.success(`Đã đính kèm tệp vào phiên hiện tại: ${fileName}`);
                }

                setIsFileManagerOpen(false);
              } catch (err) {
                toast.error("Lỗi đính kèm tệp: " + (err.response?.data?.detail || err.message));
              } finally {
                setUploadProgress(null);
              }
            });
            return;
          }
          if (isFileActionLoading) {
            toast.info('Đang xử lý tệp, vui lòng chờ hoàn tất.');
            return;
          }
          setTemplate([fileName, fileId]);
          if (activeMode === 'contract') {
            const sid = Number(session[0]);
            if (sid > 0) {
              try {
                await contractService.pinContractPath(sid, fileName);
                const data_ = await contractService.loadSession(userId);
                setSessionList(decorateContractSessions(data_));
              } catch (err) {
                console.error("Lỗi ghim template:", err);
              }
            }
          }
        }}
      />

      {/* ContractManager Modal */}
      <ContractManagerModal
        isOpen={isContractManagerOpen}
        onClose={() => setIsContractManagerOpen(false)}
        contracts={contractList}
        onRefresh={() => contractService.loadContract().then((data_) => setContractList(data_ || []))}
        svc={contractService}
      />
      {/* PREMIUM ROLE MANAGEMENT MODAL */}
      {
        isRoleModalOpen && selectedUserForRole && (
          <div className={styles.premiumModalOverlay} onClick={() => setIsRoleModalOpen(false)}>
            <div className={styles.premiumModalContent} style={{ maxWidth: 500 }} onClick={e => e.stopPropagation()}>
              <div className={styles.premiumModalHeader}>
                <h3>Quản lý vai trò: {selectedUserForRole.email}</h3>
                <button className={styles.premiumModalCloseBtn} onClick={() => setIsRoleModalOpen(false)} title="Đóng">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </button>
              </div>
              <div className={styles.premiumModalBody} style={{ padding: '32px' }}>
                <div style={{ marginBottom: '24px' }}>
                  <h4 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Vai trò hiện tại</h4>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                    {(selectedUserForRole.roles || []).length === 0 ? (
                      <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>Chưa có vai trò nào</span>
                    ) : (
                      (selectedUserForRole.roles || []).map(r => (
                        <div
                          key={r}
                          className={`${styles.premiumRoleTag} ${styles['badge-' + r]}`}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            padding: '6px 12px',
                            borderRadius: '12px',
                            fontSize: '1.0rem',
                            fontWeight: 600,
                            cursor: 'pointer'
                          }}
                          onClick={() => {
                            const newRoles = selectedUserForRole.roles.filter(x => x !== r);
                            handleChangeRole(selectedUserForRole, newRoles).then(() => {
                              setSelectedUserForRole({ ...selectedUserForRole, roles: newRoles });
                            });
                          }}
                          title="Click để xóa"
                        >
                          {r}
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div>
                  <h4 style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Thêm vai trò</h4>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                    {systemRoles
                      .filter(r => !(selectedUserForRole.roles || []).includes(r.name))
                      .length === 0 ? (
                      <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>Đã có tất cả các quyền</span>
                    ) : (
                      systemRoles
                        .filter(r => !(selectedUserForRole.roles || []).includes(r.name))
                        .map(r => (
                          <button
                            key={r.id}
                            className={styles.premiumAddRoleBtn}
                            onClick={() => {
                              const newRoles = [...(selectedUserForRole.roles || []), r.name];
                              handleChangeRole(selectedUserForRole, newRoles).then(() => {
                                setSelectedUserForRole({ ...selectedUserForRole, roles: newRoles });
                              });
                            }}
                            style={{
                              padding: '6px 16px',
                              borderRadius: '12px',
                              border: '1.5px dashed var(--border-color)',
                              background: 'transparent',
                              color: 'var(--text-main)',
                              cursor: 'pointer',
                              fontSize: '0.85rem',
                              fontWeight: 500,
                              transition: 'all 0.2s',
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6
                            }}
                          >
                            <span style={{ fontSize: '1.2rem', fontWeight: 300 }}>+</span> {r.name}
                          </button>
                        ))
                    )
                    }
                  </div>
                </div>
              </div>
              <div style={{ padding: '24px 32px', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setIsRoleModalOpen(false)}
                  style={{
                    padding: '10px 24px',
                    borderRadius: '12px',
                    background: 'var(--color-accent)',
                    border: 'none',
                    color: 'var(--text-main)',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  Hoàn tất
                </button>
              </div>
            </div>
          </div>
        )
      }

      {/* LOGIN HISTORY MODAL (PREMIUM) */}
      {
        isLoginHistoryModalOpen && selectedUserForHistory && (
          <div className={styles.premiumModalOverlay} onClick={() => setIsLoginHistoryModalOpen(false)}>
            <div className={styles.premiumModalContent} onClick={e => e.stopPropagation()}>
              <div className={styles.premiumModalHeader}>
                <h3>Lịch sử đăng nhập: {selectedUserForHistory.email}</h3>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button
                    className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}
                    onClick={() => handleDeleteLoginHistory(selectedUserForHistory.id)}
                    title="Xóa toàn bộ lịch sử đăng nhập"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"></path><path d="M10 11v6M14 11v6"></path></svg>
                    Xóa lịch sử
                  </button>
                  <button className={styles.premiumModalCloseBtn} onClick={() => setIsLoginHistoryModalOpen(false)} title="Đóng">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                  </button>
                </div>
              </div>
              <div className={styles.premiumModalBody}>
                <table className={styles.premiumTable}>
                  <thead>
                    <tr>
                      <th>Thời gian</th>
                      <th>Hành động</th>
                      <th>IP</th>
                      <th>Vị trí</th>
                      <th>ISP</th>
                      <th>Thiết bị / OS</th>
                      <th>VPN</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {loginHistory.length === 0 ? (
                      <tr><td colSpan="8" style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>Không có dữ liệu hoặc đang tải...</td></tr>
                    ) : loginHistory.map((h) => (
                      <tr key={h.id}>
                        <td>
                          <div style={{ fontWeight: 600 }}>{new Date(h.created_at).toLocaleTimeString('vi-VN')}</div>
                          <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{new Date(h.created_at).toLocaleDateString('vi-VN')}</div>
                        </td>
                        <td>
                          {h.action === 'login' ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#10b981', fontWeight: 600 }}>
                              <span style={{ width: 8, height: 8, background: '#10b981', borderRadius: '50%' }}></span> Đăng nhập
                            </div>
                          ) : (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#94a3b8', fontWeight: 600 }}>
                              <span style={{ width: 8, height: 8, background: '#94a3b8', borderRadius: '50%' }}></span> Đăng xuất
                            </div>
                          )}
                        </td>
                        <td className={styles.ipAddressCell} title={h.ip_address}>{h.ip_address}</td>
                        <td>
                          <div style={{ fontWeight: 500 }}>{h.country === 'LAN' ? 'LAN, Private' : h.country}</div>
                          {h.city && <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{h.city}</div>}
                        </td>
                        <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{h.isp || h.as_org || 'Local Network'}</td>
                        <td style={{ fontSize: '0.8rem' }}>
                          <div style={{ fontWeight: 500 }}>{h.os}</div>
                          <div style={{ color: 'var(--text-secondary)' }}>{h.browser}</div>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <div style={{
                            display: 'inline-flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            padding: '4px 8px',
                            borderRadius: '8px',
                            background: h.is_vpn_or_datacenter ? 'rgba(239, 68, 68, 0.1)' : 'rgba(16, 185, 129, 0.1)',
                            color: h.is_vpn_or_datacenter ? '#ef4444' : '#10b981',
                            minWidth: '50px'
                          }}>
                            <div style={{ width: 6, height: 6, background: 'currentColor', borderRadius: '50%', marginBottom: 2 }}></div>
                            <span style={{ fontSize: '0.7rem', fontWeight: 700 }}>{h.is_vpn_or_datacenter ? 'CÓ' : 'KHÔNG'}</span>
                          </div>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            className={`${styles.actionBtnSmall} ${styles.actionBtnDanger}`}
                            onClick={() => handleDeleteLoginHistoryEntry(h.id)}
                            title="Xóa bản ghi này"
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"></path></svg>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )
      }
      {uploadProgress && (
        <UploadProgress 
          percent={uploadProgress.percent} 
          fileName={uploadProgress.fileName} 
          status={uploadProgress.status} 
        />
      )}
    </div >
  );
}
