/**
 * Shared drag-and-drop / browse upload widget.
 * Used by Sources.jsx (local_folder library + adapter script upload) and
 * LocalLibrary.jsx (adding more files to an already-uploaded folder).
 */
import { useRef, useState } from 'react'

// Recursively walks a dropped folder's DataTransferItem entries (Chrome/Edge
// support DataTransferItem.webkitGetAsEntry()) so dragging a whole folder from
// Windows Explorer preserves its structure, same as picking one via a
// webkitdirectory <input>. Falls back to a flat file list on browsers that
// don't support the entry API.

function readEntry(entry, pathPrefix) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        try {
          Object.defineProperty(file, 'webkitRelativePath', {
            value: pathPrefix + file.name, configurable: true,
          })
        } catch {
          // Some browsers make webkitRelativePath non-configurable; the
          // upload still works, it just won't carry the folder prefix.
        }
        resolve([file])
      }, () => resolve([]))
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      const collected = []
      const readBatch = () => {
        reader.readEntries(async (entries) => {
          if (entries.length === 0) {
            const nested = await Promise.all(
              collected.map((e) => readEntry(e, `${pathPrefix}${entry.name}/`))
            )
            resolve(nested.flat())
          } else {
            collected.push(...entries)
            readBatch()
          }
        }, () => resolve([]))
      }
      readBatch()
    } else {
      resolve([])
    }
  })
}

export async function filesFromDataTransfer(dataTransfer) {
  const items = Array.from(dataTransfer.items || [])
  if (items.length && items[0].webkitGetAsEntry) {
    const entries = items.map((item) => item.webkitGetAsEntry()).filter(Boolean)
    const nested = await Promise.all(entries.map((e) => readEntry(e, '')))
    return nested.flat()
  }
  return Array.from(dataTransfer.files || [])
}

export function Dropzone({ label, hint, accept, directory, disabled, disabledHint, onFiles, children }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  const handleDrop = async (e) => {
    e.preventDefault()
    setDragOver(false)
    if (disabled) return
    const files = await filesFromDataTransfer(e.dataTransfer)
    if (files.length) onFiles(files)
  }

  const handleBrowseClick = () => {
    if (disabled) return
    inputRef.current?.click()
  }

  const handleInputChange = (e) => {
    const files = Array.from(e.target.files || [])
    e.target.value = ''  // allow re-selecting the same file/folder
    if (files.length) onFiles(files)
  }

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`rounded-lg border-2 border-dashed p-4 text-center transition-colors
          ${disabled ? 'border-gray-800 bg-gray-900/50 opacity-60' :
            dragOver ? 'border-brand-500 bg-brand-600/10' : 'border-gray-700 hover:border-gray-600'}`}
      >
        <p className="text-sm text-gray-300">{label}</p>
        {hint && <p className="text-xs text-gray-500 mt-1">{hint}</p>}
        {disabled && disabledHint && <p className="text-xs text-yellow-400 mt-2">{disabledHint}</p>}
        <button
          type="button"
          className="btn-secondary text-sm mt-3"
          onClick={handleBrowseClick}
          disabled={disabled}
        >
          {directory ? '📁 Browse Folder…' : '📄 Browse File…'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={!!directory}
          {...(directory ? { webkitdirectory: '', directory: '' } : {})}
          className="hidden"
          onChange={handleInputChange}
        />
      </div>
      {children}
    </div>
  )
}
