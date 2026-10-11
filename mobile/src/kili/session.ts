/** Device credentials. The app adapter must be expo-secure-store, never AsyncStorage. */

export interface SecretStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

export interface GatewayCredentials {
  baseUrl: string;
  secret: string;
  token: string;
}

const KEY = "kili.gateway.credentials";

export function memorySecretStore(): SecretStore {
  const values = new Map<string, string>();
  return {
    async get(key) {
      return values.get(key) ?? null;
    },
    async set(key, value) {
      values.set(key, value);
    },
    async remove(key) {
      values.delete(key);
    },
  };
}

export async function saveCredentials(store: SecretStore, credentials: GatewayCredentials): Promise<void> {
  await store.set(KEY, JSON.stringify(credentials));
}

export async function loadCredentials(store: SecretStore): Promise<GatewayCredentials | null> {
  const raw = await store.get(KEY);
  if (!raw) return null;
  const parsed = JSON.parse(raw) as Partial<GatewayCredentials>;
  if (!parsed.baseUrl || !parsed.token) return null;
  return { baseUrl: parsed.baseUrl, secret: parsed.secret ?? "", token: parsed.token };
}

export async function clearCredentials(store: SecretStore): Promise<void> {
  await store.remove(KEY);
}
