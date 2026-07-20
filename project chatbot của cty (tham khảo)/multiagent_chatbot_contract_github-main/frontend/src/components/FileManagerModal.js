"use client";
import React, { useEffect, useRef, useState } from 'react';
import styles from '../styles/FileManagerModal.module.css';
import { toast } from 'react-toastify';

export default function FileManagerModal({ isOpen, onClose, activeMode, files, onRefresh, onFileSelect, onFileDeleted, svc, currentSessionId = -1, canSelect = true, userRoles = [], isBusy = false, onBusyChange = null }) {
    const isAdmin = Array.isArray(userRoles) && userRoles.includes('root');
    const canUpload = Array.isArray(userRoles) && (userRoles.includes('root') || userRoles.includes('upload'));
    const canManageWebSources = false;
    const canDelete = isAdmin;
    const [isUploading, setIsUploading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const fileInputRef = useRef(null);

    // Multi-select state
    const [isSelectMode, setIsSelectMode] = useState(false);
    const [selectedFiles, setSelectedFiles] = useState(new Set());
    const [isBulkDeleting, setIsBulkDeleting] = useState(false);
    const [isSourceModalOpen, setIsSourceModalOpen] = useState(false);
    const [webSourceRules, setWebSourceRules] = useState([]);
    const [isSourceLoading, setIsSourceLoading] = useState(false);
    const [isSourceSaving, setIsSourceSaving] = useState(false);
    const [editingRule, setEditingRule] = useState(null);
    const [sourceForm, setSourceForm] = useState({
        rule_type: 'allow',
        match_type: 'domain',
        value: '',
        note: '',
        is_active: true,
    });

    const title = activeMode === "query" ? "Thư mục File" : "Quản lý Hợp đồng mẫu";
    const isContractMode = activeMode === "contract";
    const isProcessing = isUploading || isBusy || isBulkDeleting;

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

    const resetSourceForm = () => {
        setEditingRule(null);
        setSourceForm({
            rule_type: 'allow',
            match_type: 'domain',
            value: '',
            note: '',
            is_active: true,
        });
    };

    const loadWebSourceRules = async (silent = false) => {
        if (!canManageWebSources) return;
        if (!silent) setIsSourceLoading(true);
        try {
            const data = await requestAdminApi('/api/v1/admin/settings/web-sources');
            setWebSourceRules(Array.isArray(data) ? data : []);
        } catch (err) {
            if (!silent) {
                toast.error(`Không tải được rule nguồn web: ${err?.message || 'Không xác định'}`);
            }
        } finally {
            if (!silent) setIsSourceLoading(false);
        }
    };

    const openEditSourceRule = (rule) => {
        setEditingRule(rule);
        setSourceForm({
            rule_type: rule.rule_type || 'allow',
            match_type: rule.match_type || 'domain',
            value: rule.value || '',
            note: rule.note || '',
            is_active: Boolean(rule.is_active),
        });
    };

    const handleSaveSourceRule = async (e) => {
        e.preventDefault();
        const payload = {
            rule_type: sourceForm.rule_type,
            match_type: sourceForm.match_type,
            value: sourceForm.value,
            note: sourceForm.note,
            is_active: Boolean(sourceForm.is_active),
        };

        setIsSourceSaving(true);
        try {
            if (editingRule?.id) {
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
            resetSourceForm();
            await loadWebSourceRules(true);
        } catch (err) {
            toast.error(`Lưu rule thất bại: ${err?.message || 'Không xác định'}`);
        } finally {
            setIsSourceSaving(false);
        }
    };

    const handleDeleteSourceRule = async (ruleId) => {
        if (!window.confirm('Bạn có chắc muốn xóa rule nguồn web này?')) return;
        try {
            await requestAdminApi(`/api/v1/admin/settings/web-sources/${ruleId}`, { method: 'DELETE' });
            toast.success('Đã xóa rule nguồn web');
            await loadWebSourceRules(true);
        } catch (err) {
            toast.error(`Xóa rule thất bại: ${err?.message || 'Không xác định'}`);
        }
    };

    const handleToggleSourceRule = async (rule) => {
        try {
            await requestAdminApi(`/api/v1/admin/settings/web-sources/${rule.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: !rule.is_active }),
            });
            toast.success('Đã cập nhật trạng thái rule');
            await loadWebSourceRules(true);
        } catch (err) {
            toast.error(`Cập nhật trạng thái thất bại: ${err?.message || 'Không xác định'}`);
        }
    };

    useEffect(() => {
        if (isOpen && canManageWebSources && isSourceModalOpen) {
            loadWebSourceRules();
        }
    }, [isOpen, canManageWebSources, isSourceModalOpen]);

    const safeFiles = Array.isArray(files) ? files : [];

    const filteredFiles = searchQuery.trim()
        ? safeFiles.filter((f) => {
            const name = typeof f === 'object' && f !== null ? f.name : f;
            return name.toLowerCase().includes(searchQuery.trim().toLowerCase());
        })
        : safeFiles;

    if (!isOpen) return null;

    // Multi-select helpers
    const getFileKey = (file, idx) => {
        if (isContractMode && typeof file === 'object' && file.id !== undefined) return `id-${file.id}`;
        const name = typeof file === 'object' && file !== null ? file.name : file;
        return `${name}-${idx}`;
    };

    const toggleFileSelection = (file, idx) => {
        const key = getFileKey(file, idx);
        setSelectedFiles(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const toggleSelectAll = () => {
        if (selectedFiles.size === filteredFiles.length) {
            setSelectedFiles(new Set());
        } else {
            const allKeys = new Set(filteredFiles.map((f, i) => getFileKey(f, i)));
            setSelectedFiles(allKeys);
        }
    };

    const exitSelectMode = () => {
        setIsSelectMode(false);
        setSelectedFiles(new Set());
    };

    const handleBulkDelete = async () => {
        if (selectedFiles.size === 0) return;
        const count = selectedFiles.size;
        if (!confirm(`Bạn có chắc chắn muốn xóa ${count} tệp đã chọn?`)) return;

        setIsBulkDeleting(true);
        let successCount = 0;
        let failCount = 0;

        for (let i = 0; i < filteredFiles.length; i++) {
            const file = filteredFiles[i];
            const key = getFileKey(file, i);
            if (!selectedFiles.has(key)) continue;

            try {
                if (isContractMode) {
                    if (svc.deleteTemplate && typeof file === 'object' && file.id !== undefined) {
                        await svc.deleteTemplate(file.id);
                        if (onFileDeleted) onFileDeleted(file);
                        successCount++;
                    } else {
                        failCount++;
                    }
                } else {
                    const fileName = typeof file === 'object' && file !== null ? file.name : file;
                    if (svc.deleteFile) {
                        await svc.deleteFile(fileName);
                        if (onFileDeleted) onFileDeleted(fileName);
                        successCount++;
                    } else {
                        failCount++;
                    }
                }
            } catch (error) {
                console.error("Bulk delete error:", error);
                failCount++;
            }
        }

        if (successCount > 0) {
            toast.success(`Đã xóa thành công ${successCount} tệp!`);
            if (onRefresh) onRefresh();
        }
        if (failCount > 0) {
            toast.error(`${failCount} tệp xóa thất bại.`);
        }

        exitSelectMode();
        setIsBulkDeleting(false);
    };

    const handleUploadClick = () => {
        if (isProcessing) return;
        if (fileInputRef.current) {
            fileInputRef.current.click();
        }
    };

    const handleFileChange = async (e) => {
        const filesToUpload = Array.from(e.target.files);
        if (filesToUpload.length === 0) return;

        setIsUploading(true);
        if (onBusyChange) onBusyChange(true);
        let successCount = 0;
        let failCount = 0;
        let lastRes = null;

        try {
            if (isContractMode) {
                try {
                    let uploadRes = await svc.uploadFile(filesToUpload);
                    successCount = filesToUpload.length;
                    lastRes = uploadRes;
                    
                    // Auto pin the first uploaded file in contract mode
                    const firstFile = filesToUpload[0];
                    if (firstFile && onFileSelect) {
                        onFileSelect(firstFile, 0);
                    }
                } catch (err) {
                    console.error(`Upload error:`, err);
                    failCount = filesToUpload.length;
                }
            } else {
                for (const file of filesToUpload) {
                    // --- Client-side validation for non-root users ---
                    if (!isAdmin && file.size > 10 * 1024 * 1024) {
                        toast.error(`File ${file.name} quá lớn (tối đa 10MB cho tài khoản của bạn)`);
                        failCount++;
                        continue;
                    }

                    try {
                        let uploadRes;
                        const targetSessionId = currentSessionId > 0 ? currentSessionId : 0;
                        uploadRes = await svc.uploadFile(file, targetSessionId);
                        successCount++;
                        lastRes = uploadRes;
                    } catch (err) {
                        console.error(`Upload error for ${file.name}:`, err);
                        failCount++;
                    }
                }
            }

            if (successCount > 0) {
                toast.success(`Tải lên thành công ${successCount} tệp!`);
                if (onRefresh) await onRefresh(lastRes);
            }
            if (failCount > 0) {
                toast.error(`${failCount} tệp tải lên thất bại.`);
            }
        } finally {
            setIsUploading(false);
            if (onBusyChange) onBusyChange(false);
            e.target.value = null; // reset input
        }
    };

    return (
        <div className={styles.overlay} onClick={onClose}>
            <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
                <div className={styles.header}>
                    <h2>
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 10, verticalAlign: 'middle' }}>
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                        </svg>
                        {title}
                    </h2>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {canDelete && filteredFiles.length > 0 && (
                            <button
                                className={`${styles.selectModeBtn} ${isSelectMode ? styles.selectModeBtnActive : ''}`}
                                onClick={() => isSelectMode ? exitSelectMode() : setIsSelectMode(true)}
                                disabled={isProcessing}
                            >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 11 12 14 22 4"></polyline><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>
                                {isSelectMode ? 'Hủy chọn' : 'Chọn nhiều'}
                            </button>
                        )}
                        {canManageWebSources && (
                            <button
                                className={styles.sourceRulesTriggerBtn}
                                onClick={() => {
                                    setIsSourceModalOpen(true);
                                    resetSourceForm();
                                }}
                                disabled={isProcessing}
                                title="Quản lý nguồn web"
                            >
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <circle cx="12" cy="12" r="10"></circle>
                                    <line x1="2" y1="12" x2="22" y2="12"></line>
                                    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                                </svg>
                                Nguồn Web
                            </button>
                        )}
                        <button className={styles.closeBtn} onClick={onClose}>
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </button>
                    </div>
                </div>

                <div className={styles.content}>
                    {canUpload && (
                        <div
                            className={styles.uploadArea}
                            onClick={handleUploadClick}
                            style={{
                                opacity: isProcessing ? 0.65 : 1,
                                cursor: isProcessing ? 'not-allowed' : 'pointer',
                                pointerEvents: isProcessing ? 'none' : 'auto'
                            }}
                        >
                            <input
                                type="file"
                                ref={fileInputRef}
                                style={{ display: 'none' }}
                                onChange={handleFileChange}
                                multiple
                                accept=".pdf,.docx,.doc,.pptx,.ppt,.csv,.jpg,.jpeg,.png,.bmp,.tiff,.webp"
                                disabled={isProcessing}
                            />
                            {isProcessing ? (
                                <div className={styles.uploadingState}>
                                    <div className={styles.spinner}></div>
                                    <p>Đang xử lý tệp...</p>
                                </div>
                            ) : (
                                <>
                                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                                    <p><strong>Bấm vào đây</strong> để tải {isContractMode ? "hợp đồng mẫu" : "tài liệu"} mới lên</p>
                                    <span className={styles.hint}>Hỗ trợ .pdf, .docx, .pptx, .csv, .jpg, .png</span>
                                </>
                            )}
                        </div>
                    )}

                    <div className={styles.searchBar}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                        <input
                            type="text"
                            className={styles.searchInput}
                            placeholder={isContractMode ? 'Tìm kiếm mẫu hợp đồng...' : 'Tìm kiếm tập tin...'}
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>

                    <div className={styles.fileListHeader}>
                        <h3>Danh sách tập tin ({filteredFiles.length}{searchQuery.trim() ? ` / ${safeFiles.length}` : ''})</h3>
                    </div>

                    {/* Select All bar */}
                    {isSelectMode && filteredFiles.length > 0 && (
                        <div className={styles.selectAllBar} onClick={toggleSelectAll}>
                            <input
                                type="checkbox"
                                className={styles.fileCheckbox}
                                checked={selectedFiles.size === filteredFiles.length && filteredFiles.length > 0}
                                onChange={toggleSelectAll}
                                onClick={(e) => e.stopPropagation()}
                            />
                            <label>Chọn tất cả ({filteredFiles.length})</label>
                        </div>
                    )}

                    <div className={styles.fileList}>
                        {filteredFiles.length === 0 ? (
                            <div className={styles.emptyState}>{searchQuery.trim() ? 'Không tìm thấy tập tin phù hợp.' : 'Chưa có tập tin nào.'}</div>
                        ) : (
                            filteredFiles.map((file, idx) => {
                                const fileName = typeof file === 'object' && file !== null ? file.name : file;
                                const fileKey = getFileKey(file, idx);
                                const isSelected = selectedFiles.has(fileKey);
                                return (
                                    <div
                                        key={idx}
                                        className={styles.fileItem}
                                        style={isSelected ? { borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.05)' } : {}}
                                        onClick={isSelectMode ? () => toggleFileSelection(file, idx) : undefined}
                                    >
                                        {isSelectMode && (
                                            <input
                                                type="checkbox"
                                                className={styles.fileCheckbox}
                                                checked={isSelected}
                                                onChange={() => toggleFileSelection(file, idx)}
                                                onClick={(e) => e.stopPropagation()}
                                            />
                                        )}
                                        <div className={styles.fileInfo}>
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>
                                            <span className={styles.fileName} title={fileName}>{fileName}</span>
                                        </div>

                                        {!isSelectMode && (
                                            <div className={styles.fileActions}>
                                                {isContractMode && canSelect && (
                                                    <button
                                                        className={styles.selectBtn}
                                                        disabled={isProcessing}
                                                        onClick={() => {
                                                            if (onFileSelect) onFileSelect(file, idx);
                                                            toast.success(`Đã chọn mẫu: ${fileName}`);
                                                            onClose();
                                                        }}
                                                    >
                                                        Chọn mẫu này
                                                    </button>
                                                )}
                                                {!isContractMode && canSelect && (
                                                    <button
                                                        className={styles.selectBtn}
                                                        disabled={isProcessing}
                                                        onClick={async () => {
                                                            try {
                                                                if (onFileSelect) {
                                                                    await onFileSelect(fileName, idx);
                                                                }
                                                                onClose();
                                                            } catch (error) {
                                                                toast.error(error?.response?.data?.detail || error?.message || 'Đính kèm thất bại.');
                                                            }
                                                        }}
                                                    >
                                                        Đính kèm
                                                    </button>
                                                )}
                                                {canDelete && (
                                                    <button
                                                        className={styles.deleteBtn}
                                                        disabled={isProcessing}
                                                        title="Xóa tệp"
                                                        onClick={async () => {
                                                            if (confirm(`Bạn có chắc chắn muốn xóa "${fileName}"?`)) {
                                                                try {
                                                                    if (isContractMode) {
                                                                        console.log("DEBUG FILE DELETE:", file, "type:", typeof file, "id:", file?.id);
                                                                        if (svc.deleteTemplate && typeof file === 'object' && file.id !== undefined) {
                                                                            await svc.deleteTemplate(file.id);
                                                                            toast.success(`Đã xóa mẫu hợp đồng: ${fileName}`);
                                                                            if (onFileDeleted) onFileDeleted(file);
                                                                            if (onRefresh) onRefresh();
                                                                        } else {
                                                                            toast.error("Không thể xóa mẫu hợp đồng này do thiếu thông tin ID.");
                                                                        }
                                                                        return;
                                                                    }

                                                                    if (svc.deleteFile) {
                                                                        await svc.deleteFile(fileName);
                                                                        toast.success(`Đã xóa tệp: ${fileName}`);
                                                                        if (onFileDeleted) onFileDeleted(fileName);
                                                                        if (onRefresh) onRefresh();
                                                                    } else {
                                                                        toast.error("Chức năng xóa tệp chưa khả dụng.");
                                                                    }
                                                                } catch (error) {
                                                                    console.error("Delete error:", error);
                                                                    toast.error(error?.response?.data?.detail || "Xóa tệp thất bại.");
                                                                }
                                                            }
                                                        }}
                                                    >
                                                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>

                {/* Bulk Action Bar */}
                {isSelectMode && selectedFiles.size > 0 && (
                    <div className={styles.bulkActionBar}>
                        <span className={styles.bulkActionInfo}>
                            Đã chọn {selectedFiles.size} tệp
                        </span>
                        <div className={styles.bulkActionButtons}>
                            <button className={styles.bulkCancelBtn} onClick={exitSelectMode}>
                                Bỏ chọn
                            </button>
                            <button
                                className={styles.bulkDeleteBtn}
                                onClick={handleBulkDelete}
                                disabled={isBulkDeleting}
                            >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                                {isBulkDeleting ? 'Đang xóa...' : `Xóa ${selectedFiles.size} tệp`}
                            </button>
                        </div>
                    </div>
                )}

                {canManageWebSources && isSourceModalOpen && (
                    <div className={styles.sourceOverlay} onClick={() => setIsSourceModalOpen(false)}>
                        <div className={styles.sourceModal} onClick={(e) => e.stopPropagation()}>
                            <div className={styles.sourceHeader}>
                                <div>
                                    <h3>Quản lý Nguồn Web</h3>
                                    <p>Phân quyền: chỉ tài khoản có vai trò upload hoặc root.</p>
                                </div>
                                <button className={styles.closeBtn} onClick={() => setIsSourceModalOpen(false)}>
                                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                                </button>
                            </div>

                            <div className={styles.sourceBody}>
                                <form className={styles.sourceForm} onSubmit={handleSaveSourceRule}>
                                    <div className={styles.sourceGrid2}>
                                        <label className={styles.sourceLabel}>
                                            Rule type
                                            <select
                                                value={sourceForm.rule_type}
                                                onChange={(e) => setSourceForm({ ...sourceForm, rule_type: e.target.value })}
                                                className={styles.sourceInput}
                                                required
                                            >
                                                <option value="allow">allow</option>
                                                <option value="block">block</option>
                                            </select>
                                        </label>
                                        <label className={styles.sourceLabel}>
                                            Match type
                                            <select
                                                value={sourceForm.match_type}
                                                onChange={(e) => setSourceForm({ ...sourceForm, match_type: e.target.value })}
                                                className={styles.sourceInput}
                                                required
                                            >
                                                <option value="domain">domain</option>
                                                <option value="url_prefix">url_prefix</option>
                                            </select>
                                        </label>
                                    </div>

                                    <label className={styles.sourceLabel}>
                                        Giá trị ({sourceForm.match_type === 'domain' ? 'example.com' : 'https://example.com/path'})
                                        <input
                                            type="text"
                                            value={sourceForm.value}
                                            onChange={(e) => setSourceForm({ ...sourceForm, value: e.target.value })}
                                            className={styles.sourceInput}
                                            placeholder={sourceForm.match_type === 'domain' ? 'example.com' : 'https://example.com/news'}
                                            required
                                        />
                                    </label>

                                    <label className={styles.sourceLabel}>
                                        Ghi chú
                                        <input
                                            type="text"
                                            value={sourceForm.note}
                                            onChange={(e) => setSourceForm({ ...sourceForm, note: e.target.value })}
                                            className={styles.sourceInput}
                                            placeholder="Mô tả ngắn cho rule"
                                        />
                                    </label>

                                    <label className={styles.sourceCheckboxWrap}>
                                        <input
                                            type="checkbox"
                                            checked={sourceForm.is_active}
                                            onChange={(e) => setSourceForm({ ...sourceForm, is_active: e.target.checked })}
                                        />
                                        Kích hoạt rule
                                    </label>

                                    <div className={styles.sourceFormActions}>
                                        {editingRule && (
                                            <button type="button" className={styles.sourceGhostBtn} onClick={resetSourceForm}>
                                                Hủy sửa
                                            </button>
                                        )}
                                        <button type="submit" className={styles.sourcePrimaryBtn} disabled={isSourceSaving}>
                                            {isSourceSaving ? 'Đang lưu...' : editingRule ? 'Cập nhật rule' : 'Thêm rule'}
                                        </button>
                                    </div>
                                </form>

                                <div className={styles.sourceListSection}>
                                    <div className={styles.sourceListHeader}>
                                        <h4>Danh sách rule ({webSourceRules.length})</h4>
                                        <button className={styles.sourceGhostBtn} onClick={() => loadWebSourceRules()}>
                                            Làm mới
                                        </button>
                                    </div>

                                    {isSourceLoading ? (
                                        <div className={styles.sourceEmpty}>Đang tải rule nguồn web...</div>
                                    ) : webSourceRules.length === 0 ? (
                                        <div className={styles.sourceEmpty}>Chưa có rule nguồn web.</div>
                                    ) : (
                                        <div className={styles.sourceList}>
                                            {webSourceRules.map((rule) => (
                                                <div key={rule.id} className={styles.sourceItem}>
                                                    <div className={styles.sourceItemMain}>
                                                        <div className={styles.sourceBadges}>
                                                            <span className={`${styles.ruleBadge} ${rule.rule_type === 'allow' ? styles.ruleBadgeAllow : styles.ruleBadgeBlock}`}>
                                                                {rule.rule_type}
                                                            </span>
                                                            <span className={styles.ruleBadgeMuted}>{rule.match_type}</span>
                                                            <span className={`${styles.ruleBadgeMuted} ${rule.is_active ? styles.ruleActive : styles.ruleInactive}`}>
                                                                {rule.is_active ? 'active' : 'inactive'}
                                                            </span>
                                                        </div>
                                                        <div className={styles.sourceValue} title={rule.value}>{rule.value}</div>
                                                        {rule.note && <div className={styles.sourceNote}>{rule.note}</div>}
                                                    </div>
                                                    <div className={styles.sourceItemActions}>
                                                        <button className={styles.sourceGhostBtn} onClick={() => openEditSourceRule(rule)}>Sửa</button>
                                                        <button className={styles.sourceGhostBtn} onClick={() => handleToggleSourceRule(rule)}>
                                                            {rule.is_active ? 'Tắt' : 'Bật'}
                                                        </button>
                                                        <button className={styles.sourceDangerBtn} onClick={() => handleDeleteSourceRule(rule.id)}>Xóa</button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
