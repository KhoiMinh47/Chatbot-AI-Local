"use client";
import React, { useState, useRef, useEffect } from 'react';
import { toast } from 'react-toastify';
import styles from '../styles/ChatInput.module.css';

const ChatInput = ({ onSendMessage, onUpload, onRemoveAttachment, attachments = [], isLoading, placeholder = "Bạn muốn hỏi gì?", activeMode = "query", onModeChange, flowOption = "fast", onFlowChange, userRoles = [] }) => {
  const [input, setInput] = useState("");
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isToolsMenuOpen, setIsToolsMenuOpen] = useState(false);
  const [selectedFlow, setSelectedFlow] = useState(flowOption);
  const menuRef = useRef(null);
  const toolsRef = useRef(null);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  // Click outside to close menu
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setIsMenuOpen(false);
      }
      if (toolsRef.current && !toolsRef.current.contains(event.target)) {
        setIsToolsMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    setSelectedFlow(flowOption);
  }, [flowOption]);

  const handleSend = () => {
    if (!canRag && activeMode === 'query') {
      toast.error('Bạn không có quyền thực hiện truy vấn.');
      return;
    }
    if ((input.trim() || attachments.length > 0) && !isLoading) {
      // Gửi cả nội dung chữ và danh sách file đính kèm
      onSendMessage(input, attachments);
      setInput("");
    }
  };

  const isAttachmentDisabled = activeMode === 'contract' && (selectedFlow === 'fast' || selectedFlow === 'reasoning');

  const handleFileClick = () => {
    if (isLoading) {
      toast.info('Đang xử lý tệp, vui lòng chờ hoàn tất.');
      return;
    }
    if (isAttachmentDisabled) {
      toast.info('Chế độ này không hỗ trợ đính kèm tệp.');
      return;
    }
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileChange = async (e) => {
    if (isLoading) {
      e.target.value = null;
      return;
    }
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      if (!onUpload) {
        toast.error('Chưa cấu hình xử lý upload cho màn hình này.');
        e.target.value = null;
        return;
      }
      try {
        await onUpload(files);
      } catch (err) {
        console.error("Upload error:", err);
      }
    }
    e.target.value = null;
  };

  const removeFile = async (file) => {
    if (isLoading) {
      toast.info('Đang xử lý tệp, vui lòng chờ hoàn tất.');
      return;
    }
    if (!file) return;
    try {
      if (onRemoveAttachment) {
        await onRemoveAttachment(file);
      }
      const fileName = typeof file === 'string' ? file : file.name;
      toast.success(`Gỡ ${fileName} thành công!`);
    } catch (err) {
      const fileName = typeof file === 'string' ? file : file.name;
      toast.error(err?.response?.data?.detail || err?.message || `Gỡ ${fileName} thất bại!`);
    }
  };

  const getFileIcon = (fileName) => {
    const ext = fileName.split('.').pop().toLowerCase();
    switch (ext) {
      case 'pdf': return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>;
      case 'docx':
      case 'doc': return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M12 18h4"></path><path d="M8 18h.01"></path></svg>;
      case 'xlsx':
      case 'xls': return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="8" y1="13" x2="16" y2="13"></line><line x1="8" y1="17" x2="16" y2="17"></line></svg>;
      default: return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>;
    }
  };

  const queryMenuItems = [
    { id: 'fast', title: 'Fast', desc: 'Trả lời nhanh', icon: '⚡' },
    { id: 'web_search', title: 'Web Search', desc: 'Tra cứu web có kiểm soát', icon: '🌐' },
    // { id: 'reasoning', title: 'Tư duy', desc: 'Giải quyết các vấn đề phức tạp', icon: '🧠' },
    // { id: 'pro', title: 'Pro', desc: 'Giải toán và lập trình nâng cao với 3.1 Pro', icon: '💎' },
  ];

  const contractMenuItems = [
    { id: 'fast', title: 'Fast', desc: 'Tạo hợp đồng nhanh', icon: '⚡' },
    { id: 'reasoning', title: 'Reasoning', desc: 'Tạo hợp đồng chặt chẽ hơn', icon: '🧠' },
    { id: 'templated', title: 'Templated', desc: 'Dựa trên template', icon: '🧾' },
  ];

  const menuItems = activeMode === 'contract' ? contractMenuItems : queryMenuItems;
  const selectedItem = menuItems.find((item) => item.id === selectedFlow) || menuItems[0];

  // Logic chặn quyền: 
  // - Nếu là root hoặc Create -> Được phép
  // - Nếu là RAG (không có Create/root) -> Bị chặn
  // - Nếu chưa tải xong role (mảng rỗng) -> Tạm khóa để an toàn
  const canCreateContract = Array.isArray(userRoles) && 
    userRoles.some(r => typeof r === 'string' && ['root', 'admin', 'create'].includes(r.toLowerCase()));
  const canRag = Array.isArray(userRoles) && 
    userRoles.some(r => typeof r === 'string' && ['root', 'admin', 'rag'].includes(r.toLowerCase()));
  const canUpload = Array.isArray(userRoles) && 
    userRoles.some(r => typeof r === 'string' && ['root', 'admin', 'upload'].includes(r.toLowerCase()));

  const toolOptions = [
    { 
      id: 'query', 
      label: 'Truy vấn dữ liệu', 
      icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>,
      hidden: !canRag 
    },
    { 
      id: 'contract', 
      label: 'Tạo Hợp Đồng', 
      icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>,
      hidden: !canCreateContract
    },
  ];

  const activeToolInfo = toolOptions.find(t => t.id === activeMode);

  return (
    <div className={styles.inputContainer}>
      {/* File Attachments Area */}
      {attachments.length > 0 && (
        <div className={styles.attachmentContainer}>
          {attachments.map((file, index) => {
            const fileName = typeof file === 'string' ? file : (file?.name || file?.path || `file-${index}`);
            return (
              <div key={`${fileName}-${index}`} className={styles.fileChip}>
                <div className={styles.fileIcon}>
                  {getFileIcon(fileName)}
                </div>
                <div className={styles.fileInfo}>
                  <span className={styles.fileName}>{fileName}</span>
                  <span className={styles.fileType}>{(fileName || '').split('.').pop()}</span>
                </div>
                <button
                  className={styles.removeBtn}
                  disabled={isLoading}
                  onClick={() => removeFile(file)}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                  <span className={styles.removeTooltip}>Xóa tệp</span>
                </button>
              </div>
            )
          })}
        </div>
      )}

      <textarea
        ref={textareaRef}
        className={styles.textarea}
        placeholder={
          !canRag && activeMode === 'query' 
            ? "Bạn không có quyền truy vấn dữ liệu..." 
            : activeMode === "contract" ? "Nhập yêu cầu tạo hợp đồng..." : placeholder
        }
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
          }
        }}
        rows={1}
        disabled={isLoading || (!canRag && activeMode === 'query')}
      />
      <div className={styles.bottomBar}>
        <div className={styles.leftActions}>
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            onChange={handleFileChange}
            multiple
          />
          {canUpload && (
            <button
              className={styles.iconBtn}
              title={isAttachmentDisabled ? "Không hỗ trợ đính kèm cho luồng này" : "Đính kèm tệp"}
              onClick={handleFileClick}
              disabled={isAttachmentDisabled || isLoading}
              style={{ 
                opacity: (isAttachmentDisabled || isLoading) ? 0.4 : 1, 
                cursor: (isAttachmentDisabled || isLoading) ? 'not-allowed' : 'pointer' 
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.82-2.82l8.49-8.48"></path></svg>
            </button>
          )}
          <div className={styles.toolsMenu} ref={toolsRef}>
            <button
              className={styles.toolBtn}
              disabled={isLoading}
              onClick={() => setIsToolsMenuOpen(!isToolsMenuOpen)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path></svg>
              Công cụ
            </button>

            {isToolsMenuOpen && (
              <div className={styles.toolsDropdown}>
                <div className={styles.menuHeader}>Công cụ</div>
                {toolOptions.filter(t => !t.hidden).map((tool) => (
                  <div
                    key={tool.id}
                    className={`${styles.navItem} ${tool.disabled ? styles.navItemDisabled : ''}`}
                    onClick={() => {
                      if (isLoading) {
                        return;
                      }
                      if (tool.disabled) {
                        return;
                      }
                      if (onModeChange) onModeChange(tool.id);
                      setIsToolsMenuOpen(false);
                    }}
                    style={{ cursor: tool.disabled ? 'not-allowed' : 'pointer' }}
                  >
                    <span className={styles.navIcon} style={{ opacity: tool.disabled ? 0.5 : 1 }}>{tool.icon}</span>
                    <span style={{ color: tool.disabled ? 'var(--text-secondary)' : 'inherit' }}>{tool.label}</span>
                    {activeMode === tool.id && (
                      <svg className={styles.checkIcon} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" style={{ marginLeft: 'auto' }}><polyline points="20 6 9 17 4 12"></polyline></svg>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Hiện pill cho mode đang chọn */}
          {activeToolInfo && (
            <div className={styles.toolPillsContainer}>
              <div className={styles.toolPill}>
                <span className={styles.toolPillIcon}>{activeToolInfo.icon}</span>
                <span className={styles.toolPillLabel}>{activeToolInfo.label}</span>
              </div>
            </div>
          )}
        </div>

        <div className={styles.rightActions} ref={menuRef}>
          <div className={styles.modelSelector}>
            <button
              className={styles.selectorBtn}
              disabled={isLoading}
              onClick={() => setIsMenuOpen(!isMenuOpen)}
            >
              {selectedItem?.title || 'Nhanh'}
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6"></path></svg>
            </button>

            {isMenuOpen && (
              <div className={styles.dropdownMenu}>
                {menuItems.map((item) => (
                  <div
                    key={item.id}
                    className={styles.menuItem}
                    onClick={() => {
                      if (isLoading) return;
                      setSelectedFlow(item.id);
                      if (onFlowChange) onFlowChange(item.id);
                      setIsMenuOpen(false);
                    }}
                  >
                    <div className={styles.itemContent}>
                      <span className={styles.itemTitle}>{item.title}</span>
                      <span className={styles.itemDesc}>{item.desc}</span>
                    </div>
                    {selectedFlow === item.id && (
                      <svg className={styles.checkIcon} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"></polyline></svg>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {isLoading && (
            <div className={styles.loadingSpinner}>
              <img src="/Spinner@1x-1.0s-200px-200px.gif" alt="Loading..." />
            </div>
          )}
          <button
            className={styles.iconBtn}
            onClick={handleSend}
            disabled={isLoading || (!input.trim() && attachments.length === 0) || (!canRag && activeMode === 'query')}
            style={{ 
              color: (input.trim() || attachments.length > 0) ? 'var(--text-primary)' : 'var(--text-secondary)',
              opacity: (!canRag && activeMode === 'query') ? 0.3 : 1,
              cursor: (!canRag && activeMode === 'query') ? 'not-allowed' : 'pointer'
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatInput;
