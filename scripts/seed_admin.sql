-- Create schema if not exists
CREATE SCHEMA IF NOT EXISTS app;

-- Create users table
CREATE TABLE IF NOT EXISTS app.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT true,
    is_verified BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index on email
CREATE INDEX IF NOT EXISTS idx_users_email ON app.users(email);

-- Insert admin user (password: 123, hashed with bcrypt)
-- Password hash for "123": $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5eo6FJlJHAW7S
INSERT INTO app.users (email, password_hash, full_name, role, is_active, is_verified)
VALUES (
    'minhnhk@gmail.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5eo6FJlJHAW7S',
    'Admin User',
    'admin',
    true,
    true
)
ON CONFLICT (email) DO UPDATE SET
    password_hash = EXCLUDED.password_hash,
    role = EXCLUDED.role,
    is_verified = EXCLUDED.is_verified,
    updated_at = NOW();

-- Create conversations table
CREATE TABLE IF NOT EXISTS app.conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    mode VARCHAR(50) NOT NULL DEFAULT 'fast',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON app.conversations(user_id);

-- Create messages table
CREATE TABLE IF NOT EXISTS app.messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES app.conversations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON app.messages(conversation_id);

-- Grant permissions
GRANT ALL ON SCHEMA app TO ntc_app;
GRANT ALL ON ALL TABLES IN SCHEMA app TO ntc_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA app TO ntc_app;
