"use client";
import React, { useState, useEffect } from 'react';
import { toast } from 'react-toastify';
import { 
    getMailConfigs, addMailConfig, updateMailConfig, deleteMailConfig,
    getPrompts, addPrompt, updatePrompt, deletePrompt 
} from '../services/adminService';

/**
 * --- MAIL SERVER MANAGEMENT COMPONENT ---
 */
export function MailServerManagement({ styles }) {
    const [configs, setConfigs] = useState([]);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingConfig, setEditingConfig] = useState(null);
    const [formData, setFormData] = useState({
        host: '', port: 587, user: '', password: '', from_email: '', from_name: '', is_active: false
    });

    const fetchConfigs = async () => {
        try {
            const data = await getMailConfigs();
            setConfigs(data);
        } catch (e) {
            toast.error("Lỗi khi tải cấu hình mail");
        }
    };

    // eslint-disable-next-line react-hooks/set-state-in-effect
    useEffect(() => { fetchConfigs(); }, []);

    const handleOpenModal = (config = null) => {
        if (config) {
            setEditingConfig(config);
            setFormData({ ...config });
        } else {
            setEditingConfig(null);
            setFormData({ host: '', port: 587, user: '', password: '', from_email: '', from_name: '', is_active: false });
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
            toast.error("Lỗi: " + (err.response?.data?.detail || err.message));
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
 * --- PROMPT MANAGEMENT COMPONENT ---
 */
export function PromptManagement({ styles }) {
    const [prompts, setPrompts] = useState([]);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingPrompt, setEditingPrompt] = useState(null);
    const [formData, setFormData] = useState({ name: '', content: '', description: '', is_active: true });

    const fetchPrompts = async () => {
        try {
            const data = await getPrompts();
            setPrompts(data);
        } catch (e) {
            toast.error("Lỗi khi tải prompts");
        }
    };

    // eslint-disable-next-line react-hooks/set-state-in-effect
    useEffect(() => { fetchPrompts(); }, []);

    const handleOpenModal = (p = null) => {
        if (p) {
            setEditingPrompt(p);
            setFormData({ ...p });
        } else {
            setEditingPrompt(null);
            setFormData({ name: '', content: '', description: '', is_active: true });
        }
        setIsModalOpen(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editingPrompt) {
                await updatePrompt(editingPrompt.id, formData);
                toast.success("Đã cập nhật prompt");
            } else {
                await addPrompt(formData);
                toast.success("Đã thêm prompt mới");
            }
            setIsModalOpen(false);
            fetchPrompts();
        } catch (err) {
            toast.error("Lỗi: " + (err.response?.data?.detail || err.message));
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm("Bạn có chắc muốn xóa prompt này?")) return;
        try {
            await deletePrompt(id);
            toast.success("Đã xóa");
            fetchPrompts();
        } catch (e) {
            toast.error("Lỗi khi xóa");
        }
    };

    return (
        <div style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h3 style={{ margin: 0 }}>Quản lý Prompts</h3>
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
                            <th style={{ width: '20%' }}>Tên định danh</th>
                            <th style={{ width: '40%' }}>Nội dung vắn tắt</th>
                            <th style={{ width: '20%' }}>Mô tả</th>
                            <th style={{ width: '10%' }}>Trạng thái</th>
                            <th style={{ width: '10%' }}>Hành động</th>
                        </tr>
                    </thead>
                    <tbody>
                        {prompts.length === 0 ? (
                            <tr><td colSpan="5" style={{ textAlign: 'center', padding: '20px' }}>Chưa có prompt nào</td></tr>
                        ) : prompts.map(p => (
                            <tr key={p.id}>
                                <td style={{ fontWeight: 700, color: '#2563eb' }}>{p.name}</td>
                                <td>
                                    <div style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85rem' }}>
                                        {p.content}
                                    </div>
                                </td>
                                <td style={{ fontSize: '0.85rem' }}>{p.description}</td>
                                <td>
                                    <span style={{ 
                                        padding: '2px 6px', borderRadius: '4px', fontSize: '0.75rem',
                                        background: p.is_active ? 'rgba(16, 185, 129, 0.1)' : 'rgba(148, 163, 184, 0.1)',
                                        color: p.is_active ? '#10b981' : '#94a3b8', border: `1px solid ${p.is_active ? '#10b981' : '#94a3b8'}`
                                     }}>
                                        {p.is_active ? "Kích hoạt" : "Tạm dừng"}
                                    </span>
                                </td>
                                <td>
                                    <div style={{ display: 'flex', gap: '8px' }}>
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
                    <div style={{ background: 'var(--bg-main)', padding: '24px', borderRadius: '16px', width: '100%', maxWidth: '700px', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
                        <h4 style={{ margin: '0 0 20px 0' }}>{editingPrompt ? "Sửa Prompt" : "Thêm Prompt mới"}</h4>
                        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div>
                                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Tên định danh (VD: RAG_SYSTEM_PROMPT)</label>
                                <input 
                                    type="text" 
                                    value={formData.name} 
                                    onChange={e => setFormData({...formData, name: e.target.value})} 
                                    style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} 
                                    required 
                                    disabled={!!editingPrompt}
                                />
                                {editingPrompt && <small style={{ color: '#94a3b8' }}>Không thể đổi tên định danh sau khi tạo</small>}
                            </div>
                            <div>
                                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Mô tả ngắn</label>
                                <input type="text" value={formData.description} onChange={e => setFormData({...formData, description: e.target.value})} style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Nội dung Prompt</label>
                                <textarea 
                                    value={formData.content} 
                                    onChange={e => setFormData({...formData, content: e.target.value})} 
                                    style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'transparent', color: 'inherit', minHeight: '250px', fontFamily: 'monospace', fontSize: '0.9rem' }} 
                                    required 
                                />
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <input type="checkbox" checked={formData.is_active} onChange={e => setFormData({...formData, is_active: e.target.checked})} id="is_active_prompt" />
                                <label htmlFor="is_active_prompt" style={{ fontSize: '0.9rem' }}>Kích hoạt</label>
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
