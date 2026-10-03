/* The header: brand, notifications, user.
 *
 * The bell shows today's care tasks. That is the decision recorded in
 * docs/MIGRATION_AUDIT.md section 5: section 11 asks for a Notifications item, but
 * there is no notification-feed endpoint — only preferences and the email delivery
 * log — and inventing one would be a schema change. Today's care is what the user
 * can actually act on, and it matches section 32's "internal reminders".
 */

import { NavLink, useNavigate } from 'react-router-dom'
import { useMe } from '../api/profile'
import { useDashboard, actionLabel } from '../api/careTasks'
import { useAuth } from '../auth/context'
import HeaderMenu from './HeaderMenu'

const BellIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18 8.5a6 6 0 1 0-12 0c0 6-2 7.5-2 7.5h16s-2-1.5-2-7.5z" />
    <path d="M10.5 19.5a2 2 0 0 0 3 0" />
  </svg>
)

const UserIcon = (
  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="8.5" r="3.5" />
    <path d="M5 20c0-3.3 3.1-5.5 7-5.5s7 2.2 7 5.5" />
  </svg>
)

export default function Header({
  onToggleSidebar,
  collapsed,
}: {
  onToggleSidebar: () => void
  collapsed: boolean
}) {
  return (
    <header className="pc-header">
      <button
        type="button"
        className="pc-iconbtn pc-sidebar-toggle"
        onClick={onToggleSidebar}
        aria-label={collapsed ? 'הרחבת התפריט' : 'כיווץ התפריט'}
        aria-expanded={!collapsed}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <NavLink to="/" className="pc-brand">
        <img src="/favicon.svg" alt="" width="28" height="28" />
        <span>PlantCare</span>
      </NavLink>

      <div className="pc-header-actions">
        <NotificationsMenu />
        <UserMenu />
      </div>
    </header>
  )
}

function NotificationsMenu() {
  const { data, isPending, error } = useDashboard()
  const today = data?.today_care ?? []
  const overdue = data?.counts.overdue ?? 0

  return (
    <HeaderMenu label="תזכורות להיום" icon={BellIcon} badge={today.length + overdue}>
      {(close) => (
        <>
          <p className="pc-menuhead">התזכורות של היום</p>

          {isPending && <p className="pc-menuempty">טוען…</p>}

          {error && (
            <p className="pc-menuempty" role="alert">
              לא הצלחנו לטעון את התזכורות.
            </p>
          )}

          {data && today.length === 0 && overdue === 0 && (
            <p className="pc-menuempty">אין טיפולים להיום. הכול מעודכן.</p>
          )}

          {today.length > 0 && (
            <ul className="pc-menulist">
              {today.slice(0, 6).map((task) => (
                <li key={task.id}>
                  <NavLink to={`/plants/${task.plant_id}`} onClick={close}>
                    <span className="pc-menuaction">{actionLabel(task.action_type)}</span>
                    <span className="pc-menuplant">{task.plant_name ?? 'צמח'}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          )}

          {overdue > 0 && (
            <p className="pc-menufoot">
              {overdue === 1 ? 'טיפול אחד באיחור' : `${overdue} טיפולים באיחור`}
            </p>
          )}

          {data && (today.length > 0 || overdue > 0) && (
            <NavLink to="/tasks" className="pc-menulink" onClick={close}>
              לכל הטיפולים
            </NavLink>
          )}
        </>
      )}
    </HeaderMenu>
  )
}

function UserMenu() {
  const { data } = useMe()
  const { email, signOut } = useAuth()
  const navigate = useNavigate()

  return (
    <HeaderMenu label="חשבון" icon={UserIcon}>
      {(close) => (
        <>
          <p className="pc-menuhead">{data?.display_name || 'החשבון שלי'}</p>
          <p className="pc-menusub pc-ltr">{data?.email ?? email}</p>

          <NavLink to="/settings" className="pc-menulink" onClick={close}>
            הגדרות
          </NavLink>

          <button
            type="button"
            className="pc-menulink pc-menudanger"
            onClick={async () => {
              close()
              await signOut()
              navigate('/auth', { replace: true })
            }}
          >
            יציאה
          </button>
        </>
      )}
    </HeaderMenu>
  )
}
