"use client";
/* eslint-disable react-hooks/set-state-in-effect */

/**
 * Phase 8 Chat main workspace workspace page.
 *
 * Connects the Sidebar conversation listing, Message timeline, Chat composer,
 * and sliding Citation drawer metadata panel.
 */

import { useState, useEffect } from "react";
import { Sidebar } from "../components/sidebar";
import { MessageList } from "../components/message-list";
import { ChatComposer } from "../components/chat-composer";
import { CitationDrawer } from "../components/citation-drawer";
import { useChat } from "../components/use-chat";
import { apiCreateConversation, apiGetConversation, apiPatchConversation } from "../lib/api";
import { useAuth } from "../lib/auth-context";
import type { Conversation, Citation } from "../lib/types";

export default function ChatPage() {
  const { user } = useAuth();
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [selectedMode, setSelectedMode] = useState<"fast" | "reasoning">("fast");
  const [sidebarRefreshToken, setSidebarRefreshToken] = useState(0);

  const {
    messages,
    isStreaming,
    startStreaming,
    stopStreaming,
    prepareConversation,
  } = useChat(activeConvId);

  useEffect(() => {
    const currentId = activeConvId;
    if (!currentId) {
      setConversation(null);
      setSelectedMode("fast");
      return;
    }

    let active = true;
    async function load() {
      try {
        const conv = await apiGetConversation(currentId as string);
        if (active) {
          setConversation(conv);
          setSelectedMode(conv.mode);
        }
      } catch {
        /* fail silently */
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [activeConvId]);

  const handleSend = async (question: string, mode: "fast" | "reasoning", docIds: string[]) => {
    let targetConversationId = activeConvId;
    let targetConversation = conversation;

    if (!targetConversationId) {
      try {
        const created = await apiCreateConversation("Cuộc trò chuyện mới", mode);
        prepareConversation(created.id);
        setConversation(created);
        setActiveConvId(created.id);
        setSidebarRefreshToken((value) => value + 1);
        targetConversationId = created.id;
        targetConversation = created;
      } catch {
        return;
      }
    } else if (!targetConversation) {
      try {
        targetConversation = await apiGetConversation(targetConversationId);
        setConversation(targetConversation);
      } catch {
        return;
      }
    }

    // If composer mode differs from conversation mode, update it first
    if (targetConversation.mode !== mode) {
      try {
        const updated = await apiPatchConversation(targetConversationId, { mode });
        setConversation(updated);
      } catch {
        /* skip error, proceed with RAG call */
      }
    }

    void startStreaming(question, mode, docIds, targetConversationId);
  };

  const handleModeChange = (mode: "fast" | "reasoning") => {
    setSelectedMode(mode);
    setConversation((current) => (current ? { ...current, mode } : current));

    if (activeConvId) {
      void apiPatchConversation(activeConvId, { mode })
        .then(setConversation)
        .catch(() => undefined);
    }
  };

  const handleCitationClick = (citationId: string) => {
    // Find matching citation details from assistant message histories
    for (const msg of messages) {
      if (msg.role === "assistant" && msg.citations) {
        const match = msg.citations.find((c) => c.citation_id === citationId);
        if (match) {
          setActiveCitation(match);
          return;
        }
      }
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#07100e] text-[#f4f7f5]">
      {/* Conversation Sidebar */}
      <Sidebar
        activeId={activeConvId}
        onSelect={setActiveConvId}
        refreshToken={sidebarRefreshToken}
      />

      {/* Main chat window container */}
      <main className="flex-1 flex flex-col h-full overflow-hidden relative" id="main-content">
        {/* Top Header bar */}
        <header className="flex h-16 items-center justify-between border-b border-[#28433b]/60 px-6 bg-[#07100e] shrink-0">
          <div className="overflow-hidden mr-4">
            <h1 className="flex items-center gap-2 text-sm font-bold text-white truncate">
              Nemotron Nano 9B V2
              <span aria-hidden="true" className="text-slate-500">⌄</span>
            </h1>
            <p className="mt-0.5 truncate text-[10px] text-slate-400">
              {conversation?.title || "nvidia/nemotron-nano-9b-v2"}
            </p>
          </div>
          <div
            data-testid="active-mode-label"
            className="shrink-0 rounded-full border border-emerald-300/20 bg-emerald-300/5 px-3 py-1.5 text-xs font-bold text-emerald-200"
          >
            {selectedMode === "fast" ? "⚡ Fast Mode" : "🧠 Reasoning Mode"}
          </div>
        </header>

        {activeConvId ? (
          <>
            {/* Timeline Stream */}
            <MessageList
              messages={messages}
              isStreaming={isStreaming}
              onStop={stopStreaming}
              onCitationClick={handleCitationClick}
            />

            {/* Input Composer panel */}
            <div className="p-4 border-t border-[#28433b]/40 bg-[#07100e] shrink-0">
              <div className="max-w-3xl mx-auto">
                <ChatComposer
                  onSend={handleSend}
                  disabled={isStreaming}
                  mode={selectedMode}
                  onModeChange={handleModeChange}
                />
              </div>
            </div>
          </>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center p-6">
            <div className="mb-8 text-center">
              <h2 className="mb-2 text-3xl font-black tracking-tight text-white">
                Xin chào {user?.display_name || "bạn"}!
              </h2>
              <p className="text-xl text-slate-400">
                Hãy bắt đầu nhập câu hỏi của bạn
              </p>
            </div>
            <div className="w-full max-w-3xl">
              <ChatComposer
                onSend={handleSend}
                disabled={isStreaming}
                mode={selectedMode}
                onModeChange={handleModeChange}
              />
              <p className="mt-3 text-center text-[11px] text-slate-500">
                Chatbot có thể mắc sai lầm. Hãy kiểm tra những thông tin quan trọng.
              </p>
            </div>
          </div>
        )}
      </main>

      {/* Slide-out Citation Drawer previewer */}
      <CitationDrawer
        citation={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
    </div>
  );
}
