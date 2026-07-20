import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { dracula } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { normalizeApiUrl } from '../services/apiBase';

const normalizeSourcesRaw = (raw = '') => {
  const text = String(raw || '');
  const sourceHeadingRegex = /(Nguồn tham khảo\s*:?|References\s*:?)/i;
  const headingMatch = sourceHeadingRegex.exec(text);

  if (!headingMatch || headingMatch.index < 0) {
    return { head: text, chips: [] };
  }

  const splitAt = headingMatch.index;
  let head = text.slice(0, splitAt).trim();
  const tail = text.slice(splitAt);

  // Dọn dẹp đuôi rác markdown (---, **, etc.)
  head = head.replace(/\n\s*[-_*]{3,}\s*$/, '').replace(/\n\s*\*{1,2}\s*$/, '').trim();

  // ===== Bước 1: Build mapping S -> URL từ tail =====
  const mappings = {};
  const chips = [];

  // Quét toàn cục kể cả việc URL bị rớt xuống dòng, và AI nuốt mất chữ 'S' ở phần tham khảo
  const mapRegex = /\[?(?:S|-)?\s*(\d+)\]?[\s:.-]*(https?:\/\/[^\s)]+)/gi;
  let match;
  while ((match = mapRegex.exec(tail)) !== null) {
      const id = 'S' + match[1]; // Gom số và gắn chữ S cưỡng bức để chuẩn hoá theo format [S1]
      const url = match[2].replace(/[.,;:!?]+$/, ''); // Dọn dẹp dấu câu dính ở đuôi URL
      mappings[id] = url;
      chips.push({ id, url });
  }

  // Khôi phục URL dự phòng (link không chèn ID tham chiếu rành mạch)
  const leftoverTail = tail.replace(mapRegex, '');
  const rawUrlRegex = /(https?:\/\/[^\s)]+)/gi;
  while ((match = rawUrlRegex.exec(leftoverTail)) !== null) {
      const url = match[1].replace(/[.,;:!?]+$/, '');
      chips.push({ id: '', url });
  }

  // DEBUG TẠM
  console.log('MAPPINGS MỚI:', JSON.stringify(mappings));

  // Bước 2: Chèn lại link an toàn (Chỉ chèn nếu Map thật sự có tồn tại URL)
  head = head.replace(/\[(S\d+(?:\s*,\s*S\d+)*)\]/gi, (fullMatch, group) => {
    const ids = group.split(',').map(s => s.trim().toUpperCase());

    // Nếu không có ID nào có map URL, trả nguyên vẹn string ban đầu để làm chữ thường
    if (!ids.some(id => mappings[id])) {
      return fullMatch;
    }

    const parts = [];
    for (const id of ids) {
      if (mappings[id]) {
        // Gắn đuôi #citenote để báo hiệu cho CSS ở dưới
        parts.push(`[${id}](${mappings[id]}#citenote)`);
      } else {
        // Giữ nguyên text nếu ID này ảo, vì ta đã bỏ đi vòng lặp [] bao bọc ở ngoài
        parts.push(`[${id}]`);
      }
    }
    return ' ' + parts.join(', ') + ' ';
  });

  return { head, chips };
};

const BotMessage = ({ content, downloadUrl }) => {
  const resolvedDownloadUrl = normalizeApiUrl(downloadUrl);

  const { head, chips } = normalizeSourcesRaw(content);
  const [showSources, setShowSources] = useState(false);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>

      {/* Main Content */}
      <div className="markdown-body" style={{ backgroundColor: 'transparent', fontSize: 'inherit' }}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a({ href, children }) {
              const origHref = href || '';
              const isCite = origHref.includes('#citenote');
              const cleanHref = origHref.replace(/#citenote$/, '');

              if (isCite) {
                return (
                  <a
                    href={cleanHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      verticalAlign: 'super',
                      fontSize: '10px',
                      fontWeight: 'bold',
                      color: '#38bdf8',
                      textDecoration: 'none',
                      padding: '1px 5px',
                      background: 'rgba(56, 189, 248, 0.1)',
                      border: '1px solid rgba(56, 189, 248, 0.25)',
                      borderRadius: '4px',
                      margin: '0 1px',
                      transition: 'all 0.2s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = 'rgba(56, 189, 248, 0.25)';
                      e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.5)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = 'rgba(56, 189, 248, 0.1)';
                      e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.25)';
                    }}
                    title={cleanHref}
                  >
                    {children}
                  </a>
                );
              }

              // Chi hiển thị normal markdown link thuần chủng
              return (
                <a href={origHref} target="_blank" rel="noopener noreferrer" style={{ color: '#38bdf8', textDecoration: 'underline' }}>
                  {children}
                </a>
              );
            },
            code({ node, inline, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '');
              return !inline && match ? (
                <SyntaxHighlighter
                  style={dracula}
                  language={match[1]}
                  PreTag="div"
                  {...props}
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              ) : (
                <code className={className} {...props} style={{ background: 'var(--color-accent)', padding: '2px 4px', borderRadius: '4px' }}>
                  {children}
                </code>
              );
            },
            table({ children }) {
              return <table style={{ borderCollapse: 'collapse', width: '100%', margin: '10px 0' }}>{children}</table>
            },
            th({ children }) {
              return <th style={{ border: '1px solid var(--border-color)', padding: '8px', background: 'var(--color-accent)' }}>{children}</th>
            },
            td({ children }) {
              return <td style={{ border: '1px solid var(--border-color)', padding: '8px' }}>{children}</td>
            }
          }}
        >
          {head}
        </ReactMarkdown>
      </div>

      {/* Nguồn tham khảo - Collapsible */}
      {chips && chips.length > 0 && (
         <div style={{ marginTop: '4px' }}>
            <div
              onClick={() => setShowSources(!showSources)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-secondary)', fontWeight: 500, userSelect: 'none' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ transform: showSources ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.2s' }}>
                <path d="M6 9l6 6 6-6"></path>
              </svg>
              Nguồn tham khảo ({chips.length})
            </div>

            <div style={{
               maxHeight: showSources ? '500px' : '0px',
               overflow: showSources ? 'visible' : 'hidden',
               transition: 'max-height 0.3s ease',
               opacity: showSources ? '1' : '0',
            }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px' }}>
                 {chips.map((chip, idx) => {
                    let hostname = '';
                    let displayUrl = chip.url;
                    try {
                        const urlObj = new URL(chip.url);
                        hostname = urlObj.hostname;
                        const cleanHostname = hostname.replace(/^www\./i, '');
                        let cleanPath = decodeURIComponent(urlObj.pathname).replace(/\/$/, '');
                        if (cleanPath === '/') cleanPath = '';
                        displayUrl = cleanHostname + cleanPath;
                    } catch(e) {}

                    const displayText = chip.id ? `${chip.id} • ${displayUrl}` : displayUrl;
                    return (
                        <a
                          key={idx}
                          href={chip.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '6px',
                                padding: '4px 12px',
                                backgroundColor: 'rgba(56, 189, 248, 0.1)',
                                border: '1px solid rgba(56, 189, 248, 0.2)',
                                borderRadius: '8px',
                                color: '#38bdf8',
                                textDecoration: 'none',
                                fontSize: '13px',
                                fontWeight: '500',
                                maxWidth: '100%',
                                transition: 'all 0.2s ease',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = 'rgba(56, 189, 248, 0.2)';
                            e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.4)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = 'rgba(56, 189, 248, 0.1)';
                            e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.2)';
                          }}
                          title={chip.url}
                        >
                          {hostname && (
                            <img
                              src={`https://www.google.com/s2/favicons?domain=${hostname}&sz=32`}
                              alt="icon"
                              style={{ width: '14px', height: '14px', borderRadius: '2px', objectFit: 'contain' }}
                            />
                          )}
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {displayText}
                          </span>
                        </a>
                    )
                 })}
              </div>
            </div>
         </div>
      )}

      {resolvedDownloadUrl && (
        <div className="downloadChipRow">
          <a className="downloadChip" href={resolvedDownloadUrl} download>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            Tải hợp đồng
          </a>
        </div>
      )}
    </div>
  );
};

export default BotMessage;
