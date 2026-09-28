import axios from "axios";

import { api } from "./client";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>("/auth/me");
  return data;
}

export interface Credentials {
  email: string;
  password: string;
  full_name?: string;
}

export async function login(credentials: Credentials): Promise<User> {
  const { data } = await api.post<User>("/auth/login", {
    email: credentials.email,
    password: credentials.password,
  });
  return data;
}

export async function register(credentials: Credentials): Promise<User> {
  const { data } = await api.post<User>("/auth/register", {
    email: credentials.email,
    password: credentials.password,
    full_name: credentials.full_name ?? "",
  });
  return data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}

/** The kit refuses registration with 403 when the instance runs with
 * `REGISTRATION_ENABLED=false` (identity-auth §12) — recognized so the
 * login screen can drop its register action instead of showing a generic
 * failure. */
export function isRegistrationDisabled(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 403;
}
