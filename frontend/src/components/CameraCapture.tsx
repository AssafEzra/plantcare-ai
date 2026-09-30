/* Taking a photograph, inside the app.
 *
 * The first attempt at this was `capture="environment"` on a file input, and it does
 * not do what its name promises: on a desktop there is no capture device to hand the
 * request to, so every browser ignores the attribute and opens the ordinary file
 * picker — reported exactly that way, "the camera button opens the same upload popup".
 *
 * The Streamlit build it replaces used `st.camera_input`, which is `getUserMedia` with
 * a live preview, and that is the behaviour being restored here rather than invented.
 * Its two shaping facts carry over unchanged:
 *
 *   * A capture is kept deliberately. The shutter produces a still to look at, and it
 *     joins the batch only on "שמירת הצילום" — otherwise every mistimed shot has to be
 *     found and removed afterwards.
 *   * It needs a secure context. `getUserMedia` is refused over plain http, so on
 *     `http://192.168.x.x` — a phone pointed at a development server — `mediaDevices`
 *     is undefined and the caller falls back to the native input. Uploading from the
 *     device is always present, so nothing is ever unreachable.
 *
 * 1080p is requested rather than accepted: the image pipeline works to a 1600px long
 * edge and identification quality is the product, so a capture sized to the preview
 * box would be a poor photograph by construction. The rear camera is `ideal`, not
 * `exact` — a laptop has only one camera and `exact` would fail outright there.
 */

import { useEffect, useRef, useState } from 'react'
import Modal from './Modal'
import './CameraCapture.css'

type Shot = { blob: Blob; url: string }

export default function CameraCapture({
  onCapture,
  onClose,
}: {
  onCapture: (file: File) => void
  onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [shot, setShot] = useState<Shot | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  /* The stream is a hardware allocation: without the teardown the camera light stays
     on after the dialog closes. `cancelled` covers the dialog being dismissed while
     the permission prompt is still open — the stream then arrives to nobody. */
  useEffect(() => {
    let cancelled = false

    navigator.mediaDevices
      .getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      })
      .then((stream) => {
        if (cancelled) {
          for (const track of stream.getTracks()) track.stop()
          return
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          void videoRef.current.play()
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setProblem(describe(error))
      })

    return () => {
      cancelled = true
      for (const track of streamRef.current?.getTracks() ?? []) track.stop()
      streamRef.current = null
    }
  }, [])

  /* The still outlives its render, so it is revoked on the way out. The File handed
     to the caller holds the blob itself and is unaffected. */
  useEffect(() => {
    return () => {
      if (shot) URL.revokeObjectURL(shot.url)
    }
  }, [shot])

  function take() {
    const video = videoRef.current
    /* videoWidth is 0 until the first frame has decoded; drawing then yields a blank
       canvas rather than an error, which is worse than refusing. */
    if (!video?.videoWidth) {
      setProblem('המצלמה עדיין נטענת, רגע אחד')
      return
    }

    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const context = canvas.getContext('2d')
    if (!context) {
      setProblem('הצילום נכשל')
      return
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height)

    setProblem(null)
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setProblem('הצילום נכשל')
          return
        }
        setShot({ blob, url: URL.createObjectURL(blob) })
      },
      'image/jpeg',
      0.92,
    )
  }

  function retake() {
    if (shot) URL.revokeObjectURL(shot.url)
    setShot(null)
  }

  function keep() {
    if (!shot) return
    onCapture(new File([shot.blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' }))
    onClose()
  }

  return (
    <Modal title="צילום הצמח" onClose={onClose} labelledBy="pc-camera-title">
      <div className="pc-camera">
        {problem && !shot && (
          <p className="pc-formerror" role="alert">
            {problem}
          </p>
        )}

        <div className="pc-camerastage">
          {/* Kept mounted behind the still: remounting it would restart the stream,
              and a retake should be instant. `playsInline` is what stops iOS taking
              the preview fullscreen in its own player. */}
          <video
            ref={videoRef}
            className={`pc-camerafeed${shot ? ' is-hidden' : ''}`}
            playsInline
            muted
            autoPlay
          />
          {shot && <img className="pc-camerashot" src={shot.url} alt="הצילום שצולם" />}
        </div>

        <div className="pc-cameraactions">
          {shot ? (
            <>
              <button type="button" className="pc-btn" onClick={keep}>
                שמירת הצילום
              </button>
              <button type="button" className="pc-btn pc-btn-quiet" onClick={retake}>
                צילום מחדש
              </button>
            </>
          ) : (
            <button
              type="button"
              className="pc-btn"
              onClick={take}
              disabled={Boolean(problem)}
            >
              צילום
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}

/** What went wrong, in terms of what the user can do about it. */
function describe(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'ההרשאה למצלמה נדחתה. אפשר לאשר אותה בהגדרות הדפדפן, או להעלות תמונה מהמכשיר.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'לא נמצאה מצלמה במכשיר. אפשר להעלות תמונה מהמכשיר.'
  }
  if (name === 'NotReadableError') {
    return 'המצלמה תפוסה על ידי יישום אחר. אפשר לסגור אותו ולנסות שוב.'
  }
  return 'לא הצלחנו לפתוח את המצלמה. אפשר להעלות תמונה מהמכשיר.'
}
