import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload } from 'lucide-react'
import { clsx } from 'clsx'

interface Props {
  onFile: (file: File) => void
  disabled?: boolean
}

const IMAGE_MAX_PX = 1200
const IMAGE_QUALITY = 0.80

async function compressImage(file: File): Promise<File> {
  // PDFs are handled server-side; only compress raster images.
  if (file.type === 'application/pdf') return file

  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, IMAGE_MAX_PX / Math.max(bitmap.width, bitmap.height))
  const w = Math.round(bitmap.width * scale)
  const h = Math.round(bitmap.height * scale)

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, w, h)

  return new Promise((resolve) =>
    canvas.toBlob(
      (blob) => resolve(new File([blob!], file.name, { type: 'image/jpeg' })),
      'image/jpeg',
      IMAGE_QUALITY,
    ),
  )
}

export default function UploadDropzone({ onFile, disabled }: Props) {
  const onDrop = useCallback(
    async (accepted: File[]) => {
      if (!accepted[0]) return
      const file = await compressImage(accepted[0])
      onFile(file)
    },
    [onFile]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'image/*': ['.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'],
    },
    maxFiles: 1,
    disabled,
  })

  return (
    <div
      {...getRootProps()}
      className={clsx(
        'border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors',
        isDragActive
          ? 'border-brand-500 bg-brand-50'
          : 'border-gray-300 hover:border-brand-400 hover:bg-gray-50',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      <input {...getInputProps()} />
      <Upload className="mx-auto mb-3 text-gray-400" size={36} />
      {isDragActive ? (
        <p className="text-brand-600 font-medium">Drop it here…</p>
      ) : (
        <>
          <p className="font-medium text-gray-700">Drop your notes here</p>
          <p className="text-sm text-gray-400 mt-1">PDF, JPG, PNG, WEBP, HEIC — max 20 MB</p>
        </>
      )}
    </div>
  )
}
