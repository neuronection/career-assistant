import { api, TOKEN_KEY } from "./client";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
}

export async function register(email: string, password: string, full_name = ""): Promise<string> {
  const { data } = await api.post<{ access_token: string }>("/auth/register", {
    email,
    password,
    full_name,
  });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  return data.access_token;
}

export async function login(email: string, password: string): Promise<string> {
  const { data } = await api.post<{ access_token: string }>("/auth/login", { email, password });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  return data.access_token;
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>("/auth/me");
  return data;
}

export async function revokeSessions(): Promise<void> {
  await api.post("/auth/revoke-sessions");
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
}
