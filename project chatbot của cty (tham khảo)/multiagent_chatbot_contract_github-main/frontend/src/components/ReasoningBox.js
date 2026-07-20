import React, { useEffect, useState } from 'react';

const ReasoningBox = ({ title, sourceFiles, showLiveStatus = false }) => {
  const [expanded, setExpanded] = useState(false);

  const hasFiles = sourceFiles && sourceFiles.length > 0;
  const hasThinking = Boolean(title);
  const headerLabel = hasThinking ? title : "Tài liệu tham chiếu";

  // Đã vô hiệu hoá auto-expand để giữ ô trạng thái luôn đóng theo yêu cầu của giao diện chuẩn
  
  if (!hasFiles && !hasThinking) return null;

  return (
    <div style={{
      width: '100%',
      marginBottom: '8px', 
      display: 'flex',
      justifyContent: 'flex-start',
    }}>
      <div style={{
        border: '1px solid var(--border-color)',
        borderRadius: '8px',
        overflow: 'hidden',
        fontSize: '0.82rem',
        backgroundColor: 'var(--color-accent)',
        alignSelf: 'flex-start',
        minWidth: '250px',
        maxWidth: '100%',
      }}>
        {/* Header – always visible */}
        <div
          onClick={() => setExpanded(v => !v)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '8px 12px', cursor: 'pointer', userSelect: 'none',
            color: 'var(--text-secondary)', fontWeight: 500,
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {hasThinking && (
              <div style={{
                width: '6px', height: '6px',
                backgroundColor: '#3b82f6', borderRadius: '50%',
                animation: 'thinkingPulse 1.5s infinite',
                flexShrink: 0,
              }} />
            )}
            {!hasThinking && hasFiles && (
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
            )}
            <span style={{ fontStyle: hasThinking ? 'italic' : 'normal' }}>
              {headerLabel}
              {hasFiles && ` (${sourceFiles.length})`}
            </span>
          </div>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
            style={{
              transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)',
              transition: 'transform 0.25s ease',
              flexShrink: 0,
            }}>
            <path d="M6 9l6 6 6-6"></path>
          </svg>
        </div>

        {/* Details – collapsible box */}
        <div style={{
          maxHeight: expanded ? '800px' : '0px',
          overflow: expanded ? 'auto' : 'hidden',
          transition: 'max-height 0.3s ease',
        }}>
          <div style={{
            padding: '8px 12px',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
          }}>
            {/* Nếu có Thinking section */}
            {hasThinking && (
               <div style={{
                 color: 'var(--text-main)',
                 fontStyle: 'italic',
                 fontSize: '0.8rem',
                 lineHeight: 1.5,
                 whiteSpace: 'pre-wrap',
               }}>
                 {title}
               </div>
            )}

            {/* Nếu có Files section */}
            {hasFiles && (
              <div style={{
                marginTop: hasThinking ? '8px' : '0px',
                paddingTop: hasThinking ? '8px' : '0px',
                borderTop: hasThinking ? '1px dashed var(--border-color)' : 'none',
              }}>
                <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase' }}>Tài liệu tham khảo</div>
                {sourceFiles.map((name, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: '6px',
                    padding: '4px 0', color: 'var(--text-main)',
                  }}>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, color: '#3b82f6' }}>
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                    </svg>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <style>{`
          @keyframes thinkingPulse {
            0% { opacity: 0.5; transform: scale(0.8); }
            50% { opacity: 1; transform: scale(1.2); }
            100% { opacity: 0.5; transform: scale(0.8); }
          }
        `}</style>
      </div>
    </div>
  );
};

export default ReasoningBox;
