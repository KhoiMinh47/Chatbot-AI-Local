#!/usr/bin/env bash

# NTC RAG Chatbot - Run All Services with TMux
# Usage: bash ./run_all_services.sh

PROJECT_DIR="/home/ntcai/KM - Task Chatbot"
SESSION_NAME="rag-chat"

cd "$PROJECT_DIR"

# Kill existing session if it exists
tmux kill-session -t $SESSION_NAME 2>/dev/null || true

# Create new session
tmux new-session -d -s $SESSION_NAME -x 240 -y 50

# Split into windows
tmux new-window -t $SESSION_NAME -n docker
tmux new-window -t $SESSION_NAME -n logs

# Window 1: Docker Compose
tmux send-keys -t $SESSION_NAME:docker "cd '$PROJECT_DIR' && docker compose --profile core --profile app up" Enter

# Window 2: Logs
tmux send-keys -t $SESSION_NAME:logs "cd '$PROJECT_DIR' && sleep 10 && docker compose logs -f" Enter

# Attach to session
sleep 3
tmux attach-session -t $SESSION_NAME
