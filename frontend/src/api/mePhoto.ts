import { api } from "./client";

export interface PhotoState {
  photo_document_id: string | null;
}

export interface GalleryPhoto {
  document_id: string;
  filename: string;
  created_at: string;
  is_default: boolean;
}

export async function fetchPhotoState(): Promise<PhotoState> {
  const { data } = await api.get<PhotoState>("/me/photo");
  return data;
}

export async function uploadPhoto(file: File): Promise<PhotoState> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.put<PhotoState>("/me/photo", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function deletePhoto(): Promise<void> {
  await api.delete("/me/photo");
}

export async function fetchPhotoGallery(): Promise<GalleryPhoto[]> {
  const { data } = await api.get<GalleryPhoto[]>("/me/photo/gallery");
  return data;
}

export async function uploadGalleryPhoto(file: File): Promise<GalleryPhoto> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<GalleryPhoto>("/me/photo/gallery", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function setDefaultPhoto(documentId: string): Promise<void> {
  await api.put(`/me/photo/gallery/${documentId}/default`);
}

export async function deleteGalleryPhoto(documentId: string): Promise<void> {
  await api.delete(`/me/photo/gallery/${documentId}`);
}

export async function fetchPhotoBlobUrl(documentId: string): Promise<string> {
  const { data } = await api.get(`/documents/${documentId}/file`, {
    responseType: "blob",
  });
  return URL.createObjectURL(data as Blob);
}
