import { useCallback } from "react";

export interface UseFileInputOptions {
  accept?: string;
  multiple?: boolean;
  onSelect: (files: File[]) => void;
}

/**
 * Custom hook for programmatically triggering file input dialogs.
 *
 * @example
 * const { triggerFileInput } = useFileInput({
 *   accept: '.pdf',
 *   multiple: true,
 *   onSelect: (files) => console.log(files)
 * });
 *
 * <button onClick={triggerFileInput}>Upload Files</button>
 */
export function useFileInput(options: UseFileInputOptions) {
  const { accept = "*", multiple = false, onSelect } = options;

  const triggerFileInput = useCallback(
    (e?: React.MouseEvent) => {
      // SSR guard
      if (typeof window === "undefined") return;

      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }

      const input = document.createElement("input");
      input.type = "file";
      input.accept = accept;
      input.multiple = multiple;
      input.style.display = "none";

      // Cleanup function to ensure input is always removed
      const cleanup = () => {
        if (input.parentNode) {
          document.body.removeChild(input);
        }
      };

      input.onchange = (event) => {
        try {
          const target = event.target as HTMLInputElement;
          const files = Array.from(target.files || []);
          if (files.length > 0) {
            onSelect(files);
          }
        } finally {
          cleanup();
        }
      };

      // Handle cancel (user closes file picker without selecting)
      // Uses focusin event since there's no native cancel event
      const handleCancel = () => {
        // Small delay to let onchange fire first if files were selected
        setTimeout(() => {
          cleanup();
          window.removeEventListener("focus", handleCancel);
        }, 100);
      };
      window.addEventListener("focus", handleCancel, { once: true });

      // Add to DOM to ensure it works in all browsers
      document.body.appendChild(input);
      input.click();
    },
    [accept, multiple, onSelect],
  );

  return { triggerFileInput };
}

/**
 * Hook variant that also handles drag and drop events.
 *
 * @example
 * const { triggerFileInput, dragHandlers } = useFileInputWithDragDrop({
 *   accept: 'image/*',
 *   onSelect: (files) => console.log(files)
 * });
 *
 * <div {...dragHandlers} onClick={triggerFileInput}>
 *   Drop files here
 * </div>
 */
export function useFileInputWithDragDrop(options: UseFileInputOptions) {
  const { onSelect } = options;
  const { triggerFileInput } = useFileInput(options);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();

      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        onSelect(files);
      }
    },
    [onSelect],
  );

  return {
    triggerFileInput,
    dragHandlers: {
      onDragOver: handleDragOver,
      onDrop: handleDrop,
    },
  };
}
