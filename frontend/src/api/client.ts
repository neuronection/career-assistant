import axios from "axios";

export const api = axios.create({ baseURL: "/api/v1" });

export function apiDetail(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return (error.response?.data?.detail as string) ?? error.message;
  }
  return String(error);
}
