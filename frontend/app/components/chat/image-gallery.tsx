import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import type { ChatImage } from "~/hooks/useChat";

interface ImageGalleryProps {
  images: ChatImage[];
}

export function ImageGallery({ images }: ImageGalleryProps) {
  const [selectedImage, setSelectedImage] = useState<ChatImage | null>(null);

  if (images.length === 0) return null;

  return (
    <>
      <div className="flex flex-wrap gap-2 mt-2">
        {images.map((image) => (
          <button
            type="button"
            key={image.id}
            onClick={() => setSelectedImage(image)}
            className="relative group rounded-lg overflow-hidden border border-border hover:border-primary transition-colors"
          >
            <img
              src={image.url}
              alt={image.caption || image.description || "Game image"}
              className="w-32 h-32 object-cover"
            />
            {image.caption && (
              <div className="absolute inset-x-0 bottom-0 bg-black/60 text-white text-xs p-1 truncate opacity-0 group-hover:opacity-100 transition-opacity">
                {image.caption}
              </div>
            )}
          </button>
        ))}
      </div>

      <Dialog
        open={selectedImage !== null}
        onOpenChange={(open) => !open && setSelectedImage(null)}
      >
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{selectedImage?.caption || "Image"}</DialogTitle>
            {selectedImage?.description && (
              <DialogDescription>{selectedImage.description}</DialogDescription>
            )}
          </DialogHeader>
          {selectedImage && (
            <div className="flex justify-center">
              <img
                src={selectedImage.url}
                alt={selectedImage.caption || selectedImage.description || "Game image"}
                className="max-w-full max-h-[70vh] object-contain rounded-lg"
              />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
