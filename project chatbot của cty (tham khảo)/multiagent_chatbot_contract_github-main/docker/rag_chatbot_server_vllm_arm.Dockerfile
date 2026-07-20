FROM --platform=linux/arm64 vllm/vllm-openai:latest

RUN python3 -m pip install --no-cache-dir \
    https://github.com/huggingface/transformers/archive/refs/heads/main.zip
