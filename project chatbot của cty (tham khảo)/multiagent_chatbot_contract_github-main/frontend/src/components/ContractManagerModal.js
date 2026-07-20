"use client";
import React, { useState } from 'react';
import styles from '../styles/FileManagerModal.module.css';
import { toast } from 'react-toastify';

export default function ContractManagerModal({ isOpen, onClose, contracts, onRefresh, svc }) {
    const [searchQuery, setSearchQuery] = useState('');

    // Multi-select state
    const [isSelectMode, setIsSelectMode] = useState(false);
    const [selectedContracts, setSelectedContracts] = useState(new Set());
    const [isBulkDeleting, setIsBulkDeleting] = useState(false);

    if (!isOpen) return null;

    const filteredContracts = searchQuery.trim()
        ? contracts.filter((c) => c.name.toLowerCase().includes(searchQuery.trim().toLowerCase()))
        : contracts;

    const isProcessing = isBulkDeleting;

    // Multi-select helpers
    const getContractKey = (contract) => `id-${contract.id}`;

    const toggleSelection = (contract) => {
        const key = getContractKey(contract);
        setSelectedContracts(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const toggleSelectAll = () => {
        if (selectedContracts.size === filteredContracts.length) {
            setSelectedContracts(new Set());
        } else {
            const allKeys = new Set(filteredContracts.map(c => getContractKey(c)));
            setSelectedContracts(allKeys);
        }
    };

    const exitSelectMode = () => {
        setIsSelectMode(false);
        setSelectedContracts(new Set());
    };

    const handleBulkDelete = async () => {
        if (selectedContracts.size === 0) return;
        const count = selectedContracts.size;
        if (!confirm(`Bạn có chắc chắn muốn xóa ${count} hợp đồng đã chọn?`)) return;

        setIsBulkDeleting(true);
        let successCount = 0;
        let failCount = 0;

        for (const contract of filteredContracts) {
            const key = getContractKey(contract);
            if (!selectedContracts.has(key)) continue;

            try {
                if (svc.deleteContract && contract.id) {
                    await svc.deleteContract(contract.id);
                    successCount++;
                } else {
                    failCount++;
                }
            } catch (error) {
                console.error("Bulk delete error:", error);
                failCount++;
            }
        }

        if (successCount > 0) {
            toast.success(`Đã xóa thành công ${successCount} hợp đồng!`);
            if (onRefresh) onRefresh();
        }
        if (failCount > 0) {
            toast.error(`${failCount} hợp đồng xóa thất bại.`);
        }

        exitSelectMode();
        setIsBulkDeleting(false);
    };

    return (
        <div className={styles.overlay} onClick={onClose}>
            <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
                <div className={styles.header}>
                    <h2>
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 10, verticalAlign: 'middle' }}>
                            <path d="M14 2H6a2 2 0 0 0-2 2v16h16V8l-6-6z" />
                            <path d="M14 2v6h6" />
                            <path d="M16 13H8" />
                            <path d="M16 17H8" />
                            <path d="M10 9H8" />
                        </svg>
                        Hợp đồng đã tạo
                    </h2>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {filteredContracts.length > 0 && (
                            <button
                                className={`${styles.selectModeBtn} ${isSelectMode ? styles.selectModeBtnActive : ''}`}
                                onClick={() => isSelectMode ? exitSelectMode() : setIsSelectMode(true)}
                                disabled={isProcessing}
                            >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 11 12 14 22 4"></polyline><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>
                                {isSelectMode ? 'Hủy chọn' : 'Chọn nhiều'}
                            </button>
                        )}
                        <button className={styles.closeBtn} onClick={onClose}>
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </button>
                    </div>
                </div>

                <div className={styles.content}>
                    <div className={styles.searchBar}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                        <input
                            type="text"
                            className={styles.searchInput}
                            placeholder="Tìm kiếm hợp đồng..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>

                    <div className={styles.fileListHeader}>
                        <h3>Danh sách hợp đồng ({filteredContracts.length}{searchQuery.trim() ? ` / ${contracts.length}` : ''})</h3>
                    </div>

                    {/* Select All bar */}
                    {isSelectMode && filteredContracts.length > 0 && (
                        <div className={styles.selectAllBar} onClick={toggleSelectAll}>
                            <input
                                type="checkbox"
                                className={styles.fileCheckbox}
                                checked={selectedContracts.size === filteredContracts.length && filteredContracts.length > 0}
                                onChange={toggleSelectAll}
                                onClick={(e) => e.stopPropagation()}
                            />
                            <label>Chọn tất cả ({filteredContracts.length})</label>
                        </div>
                    )}

                    <div className={styles.fileList}>
                        {filteredContracts.length === 0 ? (
                            <div className={styles.emptyState}>{searchQuery.trim() ? 'Không tìm thấy hợp đồng phù hợp.' : 'Chưa có hợp đồng nào.'}</div>
                        ) : (
                            filteredContracts.map((contract, idx) => {
                                const contractId = contract.id;
                                const contractName = contract.name;
                                const contractKey = getContractKey(contract);
                                const isSelected = selectedContracts.has(contractKey);
                                return (
                                    <div
                                        key={idx}
                                        className={styles.fileItem}
                                        style={isSelected ? { borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.05)' } : {}}
                                        onClick={isSelectMode ? () => toggleSelection(contract) : undefined}
                                    >
                                        {isSelectMode && (
                                            <input
                                                type="checkbox"
                                                className={styles.fileCheckbox}
                                                checked={isSelected}
                                                onChange={() => toggleSelection(contract)}
                                                onClick={(e) => e.stopPropagation()}
                                            />
                                        )}
                                        <div className={styles.fileInfo}>
                                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>
                                            <span className={styles.fileName} title={contractName}>{contractName}</span>
                                        </div>

                                        {!isSelectMode && (
                                            <div className={styles.fileActions}>
                                                <button
                                                    className={styles.selectBtn}
                                                    style={{ marginRight: '8px', backgroundColor: '#38bdf8', color: '#0f172a' }}
                                                    onClick={async () => {
                                                        try {
                                                            if (svc.downloadContract) {
                                                                await svc.downloadContract(contractName);
                                                                toast.success(`Đang tải hộp đồng: ${contractName}`);
                                                            } else {
                                                                toast.error("Chức năng tải xuống chưa khả dụng.");
                                                            }
                                                        } catch (error) {
                                                            toast.error("Tải hợp đồng thất bại.");
                                                        }
                                                    }}
                                                >
                                                    Tải xuống
                                                </button>
                                                <button
                                                    className={styles.deleteBtn}
                                                    title="Xóa hợp đồng"
                                                    onClick={async () => {
                                                        if (confirm(`Bạn có chắc chắn muốn xóa hợp đồng "${contractName}"?`)) {
                                                            try {
                                                                if (svc.deleteContract && contractId) {
                                                                    await svc.deleteContract(contractId);
                                                                    toast.success(`Đã xóa hợp đồng: ${contractName}`);
                                                                    if (onRefresh) onRefresh();
                                                                } else {
                                                                    toast.error("Không thể xóa hợp đồng này do thiếu thông tin ID.");
                                                                }
                                                            } catch (error) {
                                                                console.error("Delete error:", error);
                                                                toast.error(error?.response?.data?.detail || "Xóa hợp đồng thất bại.");
                                                            }
                                                        }
                                                    }}
                                                >
                                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>

                {/* Bulk Action Bar */}
                {isSelectMode && selectedContracts.size > 0 && (
                    <div className={styles.bulkActionBar}>
                        <span className={styles.bulkActionInfo}>
                            Đã chọn {selectedContracts.size} hợp đồng
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
                                {isBulkDeleting ? 'Đang xóa...' : `Xóa ${selectedContracts.size} hợp đồng`}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
