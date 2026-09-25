import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, FileUp, X } from 'lucide-react'
import { clsx } from 'clsx'
import { formatBytes } from '../../lib/constants'

interface FileDropZoneProps {
  onFilesSelected: (files: File[]) => void
}

export function FileDropZone({ onFilesSelected }: FileDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDragIn = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true)
    }
  }, [])

  const handleDragOut = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      setSelectedFiles((prev) => [...prev, ...files])
    }
  }, [])

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length > 0) {
      setSelectedFiles((prev) => [...prev, ...files])
    }
  }, [])

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleSend = () => {
    if (selectedFiles.length > 0) {
      onFilesSelected(selectedFiles)
      setSelectedFiles([])
    }
  }

  return (
    <div className="space-y-3">
      <motion.div
        onDragEnter={handleDragIn}
        onDragLeave={handleDragOut}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        animate={isDragging ? { scale: 1.02 } : { scale: 1 }}
        className={clsx(
          'relative border-2 border-dashed rounded-2xl p-8 text-center transition-all duration-300',
          isDragging
            ? 'border-cyber-teal bg-cyber-teal/5'
            : 'border-frost-400/20 hover:border-frost-400/30'
        )}
      >
        <input
          type="file"
          multiple
          onChange={handleFileInput}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
        <motion.div
          animate={isDragging ? { y: -5 } : { y: 0 }}
          transition={{ type: 'spring', stiffness: 300 }}
        >
          {isDragging ? (
            <FileUp size={40} className="mx-auto text-cyber-teal mb-3" />
          ) : (
            <Upload size={40} className="mx-auto text-frost-400 mb-3" />
          )}
          <p className="text-sm text-frost-200 mb-1">
            {isDragging ? 'Drop files here' : 'Drag & drop files or click to browse'}
          </p>
          <p className="text-xs text-frost-400">
            Supports any file type
          </p>
        </motion.div>
      </motion.div>

      <AnimatePresence>
        {selectedFiles.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="glass-card p-3 space-y-2"
          >
            {selectedFiles.map((file, index) => (
              <motion.div
                key={`${file.name}-${index}`}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-white/5"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <FileUp size={14} className="text-cyber-teal flex-shrink-0" />
                  <span className="text-xs text-frost-200 truncate">{file.name}</span>
                  <span className="text-[10px] text-frost-400 flex-shrink-0">{formatBytes(file.size)}</span>
                </div>
                <button
                  onClick={() => removeFile(index)}
                  className="w-5 h-5 flex items-center justify-center rounded text-frost-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                >
                  <X size={10} />
                </button>
              </motion.div>
            ))}
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={handleSend}
              className="w-full mt-2 py-2.5 rounded-xl bg-cyber-teal/20 text-cyber-teal border border-cyber-teal/30 text-sm font-medium hover:bg-cyber-teal/30 transition-all"
            >
              Send {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''}
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
