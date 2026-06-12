import { useState, type FormEvent } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { useNavigate } from 'react-router-dom'
import { X } from 'lucide-react'
import { useCreateProject } from '@/api/queries'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui'
import { slugify } from './lib'
import styles from './CreateProjectDialog.module.css'

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === 'string') return error.detail
    return `The server rejected the request (status ${error.status}).`
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}

/**
 * "New project" dialog: name (required), slug auto-derived from name but
 * editable, description. POSTs /v1/projects; on success the project lists
 * are invalidated (see useCreateProject) and we navigate into the project.
 */
export function CreateProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const createProject = useCreateProject()

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [description, setDescription] = useState('')

  const effectiveSlug = slugTouched ? slug : slugify(name)
  const canSubmit = name.trim().length > 0 && effectiveSlug.length > 0 && !createProject.isPending

  function reset() {
    setName('')
    setSlug('')
    setSlugTouched(false)
    setDescription('')
    createProject.reset()
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    onOpenChange(next)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    createProject.mutate(
      { name: name.trim(), slug: effectiveSlug, description: description.trim() },
      {
        onSuccess: (project) => {
          handleOpenChange(false)
          navigate(`/projects/${project.slug}`)
        },
      },
    )
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content} aria-describedby={undefined}>
          <div className={styles.header}>
            <Dialog.Title className={styles.title}>New project</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className={styles.close} aria-label="Close">
                <X size={14} aria-hidden />
              </button>
            </Dialog.Close>
          </div>

          <form onSubmit={handleSubmit} className={styles.form}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="create-project-name">
                Name
              </label>
              <input
                id="create-project-name"
                className={styles.input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My eval project"
                required
              />
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor="create-project-slug">
                Slug
              </label>
              <input
                id="create-project-slug"
                className={`${styles.input} ${styles.inputMono}`}
                value={effectiveSlug}
                onChange={(e) => {
                  setSlugTouched(true)
                  setSlug(slugify(e.target.value))
                }}
                placeholder="my-eval-project"
                spellCheck={false}
                aria-describedby="create-project-slug-hint"
              />
              <span id="create-project-slug-hint" className={styles.hint}>
                Used in URLs. Auto-derived from the name.
              </span>
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor="create-project-description">
                Description
              </label>
              <textarea
                id="create-project-description"
                className={`${styles.input} ${styles.textarea}`}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What is being evaluated?"
                rows={3}
              />
            </div>

            {createProject.isError && (
              <p className={styles.error} role="alert">
                {errorMessage(createProject.error)}
              </p>
            )}

            <div className={styles.actions}>
              <Dialog.Close asChild>
                <Button variant="secondary">Cancel</Button>
              </Dialog.Close>
              <Button type="submit" loading={createProject.isPending} disabled={!canSubmit}>
                Create project
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
