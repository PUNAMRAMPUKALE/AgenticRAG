-- Production RLS for AgenticRAG.
-- This app uses Google `sub` (text), not Supabase auth.users / auth.uid().
-- The API sets: app.current_user_id, app.is_manager, app.service_role
-- then SET ROLE agenticrag_app so the table owner cannot skip RLS.

CREATE ROLE IF NOT EXISTS agenticrag_app NOINHERIT NOSUPERUSER;
GRANT agenticrag_app TO CURRENT_USER;

CREATE OR REPLACE FUNCTION app_current_user_id()
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(btrim(current_setting('app.current_user_id', true)), '');
$$;

CREATE OR REPLACE FUNCTION app_is_manager()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
  SELECT lower(COALESCE(current_setting('app.is_manager', true), 'false')) IN ('true', 't', '1', 'yes');
$$;

CREATE OR REPLACE FUNCTION app_is_service()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
  SELECT lower(COALESCE(current_setting('app.service_role', true), 'false')) IN ('true', 't', '1', 'yes');
$$;

CREATE TABLE IF NOT EXISTS user_profiles (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    full_name TEXT,
    is_manager BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS requests (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    session_id VARCHAR(36),
    user_query TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_requests_user_created ON requests (user_id, created_at DESC);

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS extra JSONB NOT NULL DEFAULT '{}'::jsonb;

INSERT INTO user_profiles (id, email, full_name)
SELECT DISTINCT c.user_id, c.user_id, NULL
FROM conversations c
WHERE NOT EXISTS (SELECT 1 FROM user_profiles p WHERE p.id = c.user_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_conversations_user_profile'
    ) THEN
        ALTER TABLE conversations
            ADD CONSTRAINT fk_conversations_user_profile
            FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO agenticrag_app;
GRANT SELECT, INSERT, UPDATE ON TABLE user_profiles, requests, conversations, messages, knowledge_ingest_runs TO agenticrag_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO agenticrag_app;
REVOKE DELETE ON TABLE user_profiles, requests, conversations, messages, knowledge_ingest_runs FROM agenticrag_app;

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE requests FORCE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge_ingest_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_ingest_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_profiles_select_own ON user_profiles;
DROP POLICY IF EXISTS user_profiles_select_manager ON user_profiles;
DROP POLICY IF EXISTS user_profiles_insert_own ON user_profiles;
DROP POLICY IF EXISTS user_profiles_update_own ON user_profiles;
DROP POLICY IF EXISTS user_profiles_update_manager ON user_profiles;
DROP POLICY IF EXISTS user_profiles_service ON user_profiles;
DROP POLICY IF EXISTS user_profiles_deny_delete ON user_profiles;

CREATE POLICY user_profiles_select_own ON user_profiles
    FOR SELECT USING (app_is_service() OR app_current_user_id() = id);
CREATE POLICY user_profiles_select_manager ON user_profiles
    FOR SELECT USING (app_is_manager());
CREATE POLICY user_profiles_insert_own ON user_profiles
    FOR INSERT WITH CHECK (app_is_service() OR app_current_user_id() = id);
CREATE POLICY user_profiles_update_own ON user_profiles
    FOR UPDATE
    USING (app_current_user_id() = id)
    WITH CHECK (app_current_user_id() = id AND is_manager IS NOT DISTINCT FROM FALSE);
CREATE POLICY user_profiles_update_manager ON user_profiles
    FOR UPDATE USING (app_is_manager()) WITH CHECK (app_is_manager());
CREATE POLICY user_profiles_service ON user_profiles
    FOR ALL USING (app_is_service()) WITH CHECK (app_is_service());
CREATE POLICY user_profiles_deny_delete ON user_profiles
    FOR DELETE USING (false);

DROP POLICY IF EXISTS requests_select_own ON requests;
DROP POLICY IF EXISTS requests_select_manager ON requests;
DROP POLICY IF EXISTS requests_insert_own ON requests;
DROP POLICY IF EXISTS requests_service ON requests;
DROP POLICY IF EXISTS requests_deny_delete ON requests;

CREATE POLICY requests_select_own ON requests
    FOR SELECT USING (app_is_service() OR app_current_user_id() = user_id);
CREATE POLICY requests_select_manager ON requests
    FOR SELECT USING (app_is_manager());
CREATE POLICY requests_insert_own ON requests
    FOR INSERT WITH CHECK (app_is_service() OR app_current_user_id() = user_id);
CREATE POLICY requests_service ON requests
    FOR ALL USING (app_is_service()) WITH CHECK (app_is_service());
CREATE POLICY requests_deny_delete ON requests
    FOR DELETE USING (false);

DROP POLICY IF EXISTS conversations_select_own ON conversations;
DROP POLICY IF EXISTS conversations_select_manager ON conversations;
DROP POLICY IF EXISTS conversations_insert_own ON conversations;
DROP POLICY IF EXISTS conversations_update_own ON conversations;
DROP POLICY IF EXISTS conversations_update_manager ON conversations;
DROP POLICY IF EXISTS conversations_service ON conversations;
DROP POLICY IF EXISTS conversations_deny_delete ON conversations;

CREATE POLICY conversations_select_own ON conversations
    FOR SELECT USING (app_is_service() OR app_current_user_id() = user_id);
CREATE POLICY conversations_select_manager ON conversations
    FOR SELECT USING (app_is_manager());
CREATE POLICY conversations_insert_own ON conversations
    FOR INSERT WITH CHECK (app_is_service() OR app_current_user_id() = user_id);
CREATE POLICY conversations_update_own ON conversations
    FOR UPDATE USING (app_current_user_id() = user_id) WITH CHECK (app_current_user_id() = user_id);
CREATE POLICY conversations_update_manager ON conversations
    FOR UPDATE USING (app_is_manager()) WITH CHECK (app_is_manager());
CREATE POLICY conversations_service ON conversations
    FOR ALL USING (app_is_service()) WITH CHECK (app_is_service());
CREATE POLICY conversations_deny_delete ON conversations
    FOR DELETE USING (false);

DROP POLICY IF EXISTS messages_select_own ON messages;
DROP POLICY IF EXISTS messages_select_manager ON messages;
DROP POLICY IF EXISTS messages_insert_own ON messages;
DROP POLICY IF EXISTS messages_service ON messages;
DROP POLICY IF EXISTS messages_deny_delete ON messages;

CREATE POLICY messages_select_own ON messages
    FOR SELECT USING (
        app_is_service()
        OR EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.session_id = messages.session_id
              AND c.user_id = app_current_user_id()
        )
    );
CREATE POLICY messages_select_manager ON messages
    FOR SELECT USING (app_is_manager());
CREATE POLICY messages_insert_own ON messages
    FOR INSERT WITH CHECK (
        app_is_service()
        OR EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.session_id = messages.session_id
              AND c.user_id = app_current_user_id()
        )
    );
CREATE POLICY messages_service ON messages
    FOR ALL USING (app_is_service()) WITH CHECK (app_is_service());
CREATE POLICY messages_deny_delete ON messages
    FOR DELETE USING (false);

DROP POLICY IF EXISTS ingest_runs_select_manager ON knowledge_ingest_runs;
DROP POLICY IF EXISTS ingest_runs_service ON knowledge_ingest_runs;
DROP POLICY IF EXISTS ingest_runs_deny_delete ON knowledge_ingest_runs;

CREATE POLICY ingest_runs_select_manager ON knowledge_ingest_runs
    FOR SELECT USING (app_is_manager() OR app_is_service());
CREATE POLICY ingest_runs_service ON knowledge_ingest_runs
    FOR ALL USING (app_is_service()) WITH CHECK (app_is_service());
CREATE POLICY ingest_runs_deny_delete ON knowledge_ingest_runs
    FOR DELETE USING (false);
