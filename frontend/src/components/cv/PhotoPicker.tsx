import { useEffect, useState } from "react";
import { ImageOff, Star } from "lucide-react";
import { UploadDropzone } from "@neuronection/assistant-ui";
import { fetchPhotoBlobUrl, type GalleryPhoto } from "@/api/mePhoto";
import { Button } from "@/components/ui";

interface PhotoPickerProps {
  photos: GalleryPhoto[];
  photoId: string;
  uploading: boolean;
  onSelect: (photoId: string) => void;
  onUpload: (file: File) => void;
  onError: (error: string) => void;
}

type ThumbMap = Record<string, string>;

export function PhotoPicker({
  photos,
  photoId,
  uploading,
  onSelect,
  onUpload,
  onError,
}: PhotoPickerProps) {
  const [thumbs, setThumbs] = useState<ThumbMap>({});
  const selected = photos.find((photo) => photo.document_id === photoId);

  useEffect(() => {
    let cancelled = false;
    const missing = photos.filter((photo) => !thumbs[photo.document_id]);
    if (missing.length === 0) return;
    (async () => {
      for (const photo of missing) {
        try {
          const url = await fetchPhotoBlobUrl(photo.document_id);
          if (cancelled) {
            URL.revokeObjectURL(url);
            return;
          }
          setThumbs((current) => ({ ...current, [photo.document_id]: url }));
        } catch {
          onError(`Could not load preview for ${photo.filename}.`);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photos]);

  return (
    <div className="space-y-2" data-testid="photo-picker-card">
      <div className="flex items-center gap-2.5">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-full border border-[var(--as-border)] bg-[var(--as-muted)]">
          {photoId && thumbs[photoId] ? (
            <img
              src={thumbs[photoId]}
              alt={selected?.filename ?? "Selected photo"}
              className="h-full w-full object-cover"
              data-testid="photo-preview"
            />
          ) : (
            <ImageOff className="h-5 w-5 text-[var(--as-muted-fg)]" aria-hidden />
          )}
        </div>
        <div className="min-w-0 flex-1 text-xs">
          <p className="font-medium text-[var(--as-fg)]">
            {photoId ? (selected?.filename ?? "Selected photo") : "No photo on this CV"}
          </p>
          <button
            type="button"
            className="text-[var(--as-muted-fg)] underline-offset-2 hover:text-[var(--as-fg)] hover:underline"
            onClick={() => onSelect("")}
            disabled={!photoId}
            data-testid="photo-use-default"
          >
            Use profile default
          </button>
        </div>
      </div>

      {photos.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="photo-gallery-strip">
          {photos.map((photo) => (
            <button
              key={photo.document_id}
              type="button"
              onClick={() => onSelect(photo.document_id)}
              aria-pressed={photo.document_id === photoId}
              aria-label={`Use ${photo.filename}`}
              title={photo.is_default ? `${photo.filename} (profile default)` : photo.filename}
              data-testid={`photo-choice-${photo.document_id}`}
              className={`relative h-11 w-11 overflow-hidden rounded-lg border-2 transition-colors ${
                photo.document_id === photoId
                  ? "border-[var(--as-accent)]"
                  : "border-transparent hover:border-[var(--as-border)]"
              }`}
            >
              {thumbs[photo.document_id] ? (
                <img
                  src={thumbs[photo.document_id]}
                  alt=""
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="flex h-full w-full items-center justify-center bg-[var(--as-muted)]">
                  <ImageOff className="h-4 w-4 text-[var(--as-muted-fg)]" aria-hidden />
                </span>
              )}
              {photo.is_default && (
                <Star
                  className="absolute bottom-0.5 right-0.5 h-3 w-3 fill-amber-400 text-amber-500"
                  aria-label="Profile default"
                />
              )}
            </button>
          ))}
        </div>
      )}

      <UploadDropzone
        variant="row"
        multiple={false}
        accept="image/png,image/jpeg,image/webp"
        uploading={uploading}
        label="Drop a photo or click to upload"
        hint="PNG, JPEG or WebP · max 2 MB — added to your gallery"
        onFiles={(files) => {
          const file = files[0];
          if (file) onUpload(file);
        }}
      />

      {photos.length > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => onSelect("")}
          data-testid="photo-clear"
        >
          Remove photo from this CV
        </Button>
      )}
    </div>
  );
}
