/**
 * Talks to the Home Assistant the repository's docker-compose already provides.
 *
 * The suite deliberately reuses that instance instead of booting one of its
 * own. A fresh clone has no `.storage`, so global setup onboards the instance
 * through the API when it is still fresh (see `ensureOnboarded`); an instance
 * that is already onboarded is used as it is. Everything the suite writes goes
 * into a dashboard of its own, so a manual playground stays intact.
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const E2E_DIR = resolve(here, '..');
const REPO_ROOT = resolve(E2E_DIR, '../..');
const TOKEN_FILE = resolve(E2E_DIR, '.auth.json');

/** Read from the compose file so the suite cannot drift from the environment. */
function portFromCompose(): string {
  const compose = readFileSync(resolve(REPO_ROOT, 'docker-compose.yml'), 'utf8');
  const match = compose.match(/'(\d+):8123'/) ?? compose.match(/"(\d+):8123"/);
  if (!match) throw new Error('No published Home Assistant port found in docker-compose.yml');
  return match[1];
}

export const PORT = process.env.HA_E2E_PORT ?? portFromCompose();
export const BASE_URL = `http://127.0.0.1:${PORT}`;
export const USERNAME = process.env.HA_E2E_USER ?? 'admin';
export const PASSWORD = process.env.HA_E2E_PASSWORD ?? 'password';

/** Brings the repository's own compose environment up if it is not running. */
export function ensureRunning(): void {
  execFileSync('docker', ['compose', 'up', '-d'], { cwd: REPO_ROOT, stdio: 'inherit' });
}

export async function waitForFrontend(timeoutMs = 180_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      // Not /api/onboarding: that endpoint is gone once onboarding is done.
      const res = await fetch(`${BASE_URL}/manifest.json`);
      if (res.ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`Home Assistant did not answer at ${BASE_URL} within ${timeoutMs}ms`);
}

interface OnboardingStep {
  step: string;
  done: boolean;
}

/**
 * Onboards a brand-new Home Assistant through its API, the same calls the
 * onboarding screen makes, so a clean checkout (or CI) needs no pre-seeded
 * `.storage`. Does nothing when onboarding is already complete.
 */
export async function ensureOnboarded(): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/onboarding`);
  // The endpoint is gone (404) once onboarding has finished.
  if (res.status === 404) return;
  if (!res.ok) throw new Error(`reading onboarding state failed: ${res.status}`);
  const steps = (await res.json()) as OnboardingStep[];
  const pending = (name: string) => steps.some((s) => s.step === name && !s.done);
  if (!pending('user')) {
    if (steps.every((s) => s.done)) return;
    throw new Error(
      'Home Assistant is partly onboarded and the suite has no tokens for it - remove config/.storage and rerun.',
    );
  }

  const clientId = `${BASE_URL}/`;
  const json = { 'Content-Type': 'application/json' };
  const created = await fetch(`${BASE_URL}/api/onboarding/users`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify({
      client_id: clientId,
      name: 'Admin',
      username: USERNAME,
      password: PASSWORD,
      language: 'en',
    }),
  });
  if (!created.ok) throw new Error(`onboarding the user failed: ${created.status} ${await created.text()}`);
  const { auth_code: code } = (await created.json()) as { auth_code: string };

  const tokenRes = await fetch(`${BASE_URL}/auth/token`, {
    method: 'POST',
    body: new URLSearchParams({ grant_type: 'authorization_code', code, client_id: clientId }),
  });
  if (!tokenRes.ok) throw new Error(`exchanging the onboarding code failed: ${tokenRes.status}`);
  const { access_token: token } = (await tokenRes.json()) as { access_token: string };

  const authed = { ...json, Authorization: `Bearer ${token}` };
  for (const [step, body] of [
    ['core_config', {}],
    ['analytics', {}],
    ['integration', { client_id: clientId, redirect_uri: `${BASE_URL}/?auth_callback=1` }],
  ] as const) {
    const done = await fetch(`${BASE_URL}/api/onboarding/${step}`, {
      method: 'POST',
      headers: authed,
      body: JSON.stringify(body),
    });
    if (!done.ok) throw new Error(`onboarding step ${step} failed: ${done.status} ${await done.text()}`);
  }
}

export interface Tokens {
  access_token: string;
}

export function saveTokens(tokens: Tokens): void {
  writeFileSync(TOKEN_FILE, JSON.stringify(tokens, null, 2));
}

export function readTokens(): Tokens {
  if (!existsSync(TOKEN_FILE)) throw new Error('No token file - did global setup run?');
  return JSON.parse(readFileSync(TOKEN_FILE, 'utf8')) as Tokens;
}

/**
 * Sends one command over the websocket API and returns its result. Node ships a
 * WebSocket client, so this needs no dependency, and it is the same API the
 * frontend itself speaks.
 */
export async function callWebsocket<T = unknown>(message: Record<string, unknown>): Promise<T> {
  const token = readTokens().access_token;
  const socket = new WebSocket(`ws://127.0.0.1:${PORT}/api/websocket`);

  return new Promise<T>((resolve_, reject) => {
    const fail = (reason: string) => {
      socket.close();
      reject(new Error(reason));
    };
    const timer = setTimeout(() => fail('websocket timed out'), 30_000);

    socket.addEventListener('error', () => fail('websocket error'));
    socket.addEventListener('message', (event) => {
      const payload = JSON.parse(String(event.data)) as Record<string, unknown>;
      switch (payload.type) {
        case 'auth_required':
          socket.send(JSON.stringify({ type: 'auth', access_token: token }));
          return;
        case 'auth_invalid':
          clearTimeout(timer);
          fail('websocket authentication was refused');
          return;
        case 'auth_ok':
          socket.send(JSON.stringify({ id: 1, ...message }));
          return;
        case 'result': {
          clearTimeout(timer);
          socket.close();
          if (payload.success) resolve_(payload.result as T);
          else reject(new Error(`websocket command failed: ${JSON.stringify(payload.error)}`));
        }
      }
    });
  });
}

/** Puts a state on the bus, the way any client would. */
export async function setState(
  entityId: string,
  state: string,
  attributes: Record<string, unknown> = {},
): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/states/${entityId}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${readTokens().access_token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ state, attributes }),
  });
  if (!res.ok) throw new Error(`setting ${entityId} failed: ${res.status} ${await res.text()}`);
}

export async function removeState(entityId: string): Promise<void> {
  await fetch(`${BASE_URL}/api/states/${entityId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${readTokens().access_token}` },
  });
}

/**
 * Gives the caller its own dashboard.
 *
 * Every spec file asks for a different name, so specs can run in parallel
 * without fighting over one dashboard - and none of them touches whatever the
 * manual test instance has on its own dashboards.
 */
export async function useDashboard(name: string, config: Record<string, unknown>): Promise<string> {
  const urlPath = `e2e-${name}`;
  const dashboards = await callWebsocket<{ url_path: string }[]>({
    type: 'lovelace/dashboards/list',
  });
  if (!dashboards.some((dashboard) => dashboard.url_path === urlPath)) {
    await callWebsocket({
      type: 'lovelace/dashboards/create',
      url_path: urlPath,
      title: `E2E ${name}`,
      mode: 'storage',
      show_in_sidebar: false,
    });
  }
  await callWebsocket({ type: 'lovelace/config/save', url_path: urlPath, config });
  return urlPath;
}

/**
 * Waits until the core has finished starting.
 *
 * `/manifest.json` answers well before that, and the card resource is
 * registered from an EVENT_HOMEASSISTANT_STARTED listener - so a suite that
 * only waited for HTTP would read the resource store mid-startup and see
 * whatever was left there by the previous run.
 */
export async function waitForCoreRunning(timeoutMs = 180_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const config = await callWebsocket<{ state: string }>({ type: 'get_config' }).catch(() => undefined);
    if (config?.state === 'RUNNING') return;
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`Home Assistant did not reach state RUNNING within ${timeoutMs}ms`);
}

/** The Lovelace resources Home Assistant has persisted. */
export async function resources(): Promise<{ id: string; url: string }[]> {
  return callWebsocket({ type: 'lovelace/resources' });
}
