-- Recreate Phase 7 auth schema with proper structure
DROP SCHEMA IF EXISTS app CASCADE;
CREATE SCHEMA app;

-- Users table with proper columns
CREATE TABLE app.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    email VARCHAR(320) NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'user',
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_users_role CHECK (role IN ('user', 'admin')),
    CONSTRAINT ck_users_email_nonblank CHECK (length(btrim(email)) > 0),
    CONSTRAINT uq_users_tenant_email UNIQUE (tenant_id, email)
);

CREATE INDEX ix_users_tenant_id ON app.users(tenant_id);
CREATE INDEX ix_users_email ON app.users(email);

-- Refresh sessions table
CREATE TABLE app.refresh_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_refresh_sessions_token_hash UNIQUE (token_hash),
    CONSTRAINT ck_refresh_sessions_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_refresh_sessions_user_id ON app.refresh_sessions(user_id);
CREATE INDEX ix_refresh_sessions_token_hash ON app.refresh_sessions(token_hash);

-- Email verification tokens table
CREATE TABLE app.email_verification_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_email_verification_token_hash UNIQUE (token_hash),
    CONSTRAINT ck_email_verification_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_email_verification_tokens_user_id ON app.email_verification_tokens(user_id);

-- Password reset tokens table
CREATE TABLE app.password_reset_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_password_reset_token_hash UNIQUE (token_hash),
    CONSTRAINT ck_password_reset_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_password_reset_tokens_user_id ON app.password_reset_tokens(user_id);

-- Audit logs table
CREATE TABLE app.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    action VARCHAR(128) NOT NULL,
    target_type VARCHAR(64),
    target_id UUID,
    request_id UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_audit_logs_action_nonblank CHECK (length(btrim(action)) > 0)
);

CREATE INDEX ix_audit_logs_tenant_created ON app.audit_logs(tenant_id, created_at);
CREATE INDEX ix_audit_logs_actor_id ON app.audit_logs(actor_id);

-- Conversations table
CREATE TABLE app.conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    title VARCHAR(512) NOT NULL,
    mode VARCHAR(16) NOT NULL DEFAULT 'fast',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_conversations_mode CHECK (mode IN ('fast', 'reasoning')),
    CONSTRAINT ck_conversations_title_nonblank CHECK (length(btrim(title)) > 0)
);

CREATE INDEX ix_conversations_user_id ON app.conversations(user_id);
CREATE INDEX ix_conversations_tenant_id ON app.conversations(tenant_id);
CREATE INDEX ix_conversations_updated_at ON app.conversations(updated_at);

-- Messages table
CREATE TABLE app.messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES app.conversations(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX ix_messages_conversation_id ON app.messages(conversation_id);
CREATE INDEX ix_messages_created_at ON app.messages(created_at);

-- Insert admin user with proper tenant_id
INSERT INTO app.users (
    id,
    tenant_id,
    email,
    password_hash,
    display_name,
    role,
    is_verified,
    created_at,
    updated_at
) VALUES (
    gen_random_uuid(),
    '10000000-0000-4000-8000-000000000001'::UUID,
    'minhnhk@gmail.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5eo6FJlJHAW7S',
    'Admin User',
    'admin',
    TRUE,
    NOW(),
    NOW()
);

-- Grant permissions
GRANT ALL ON SCHEMA app TO ntc_app;
GRANT ALL ON ALL TABLES IN SCHEMA app TO ntc_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA app TO ntc_app;
