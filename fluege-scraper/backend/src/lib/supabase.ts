import { createClient, type SupabaseClient } from '@supabase/supabase-js';

let client: SupabaseClient | undefined;

export function getSupabaseClient(): SupabaseClient {
    if (client) {
        return client;
    }

    const url = process.env['SUPABASE_URL'];
    const key = process.env['SUPABASE_SERVICE_ROLE_KEY'];

    if (!url || !key) {
        throw new Error(
            'SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY have to be set as environment variables.',
        );
    }

    client = createClient(url, key, {
        auth: { persistSession: false },
    });

    return client;
}
