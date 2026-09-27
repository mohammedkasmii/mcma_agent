import { useState } from "react";
import type { FormEvent } from "react";
import { Button, Panel } from "@shared/ui";
import type { PlatformUser, PortalAccount, UserRole } from "@shared/types";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, ROLE_ORDER, roleLabel } from "@shared/utils/roles";
import { useAccountsQuery } from "@features/accounts/queries";
import { errorOf, useCreateUser, useResetPassword, useUpdateUser, useUsersQuery } from "./queries";
import styles from "./AdminUsers.module.css";

const MISMATCH = "Les mots de passe ne correspondent pas.";

export function AdminUsersScreen() {
  const users = useUsersQuery();
  const accountsQuery = useAccountsQuery();
  const accounts = accountsQuery.data ?? [];
  const [rowError, setRowError] = useState<string | null>(null);

  return (
    <div className="u-stack-5">
      <h1 className="t-screen-title">Utilisateurs de la plateforme</h1>
      <p className="t-secondary">
        Cette page gère les comptes de la plateforme MCMA. Elle ne concerne pas les identifiants
        du portail MCMA/MAMDA.
      </p>

      <Panel title="Rôles">
        <ul className={styles.roles}>
          {ROLE_ORDER.map((role) => (
            <li key={role}>
              <strong>{ROLE_LABELS[role]}</strong> : {ROLE_DESCRIPTIONS[role]}
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Créer un utilisateur">
        <CreateUserForm accounts={accounts} />
      </Panel>

      <Panel title="Utilisateurs">
        {rowError === null ? null : (
          <p role="alert" className={styles.error}>
            {rowError}
          </p>
        )}
        {users.isPending ? <p role="status">Chargement des utilisateurs…</p> : null}
        {users.isError ? (
          <p role="alert" className={styles.error}>
            {errorOf(users.error).message}
          </p>
        ) : null}
        {users.data ? (
          <ul className={styles.list} aria-label="Liste des utilisateurs">
            {users.data.map((user) => (
              <UserRow key={user.userId} user={user} accounts={accounts} onError={setRowError} />
            ))}
          </ul>
        ) : null}
      </Panel>
    </div>
  );
}

function accountLabels(ids: readonly string[], accounts: readonly PortalAccount[]): string {
  if (ids.length === 0) return "Aucun compte";
  return ids
    .map((id) => accounts.find((account) => account.accountId === id)?.label ?? id)
    .join(", ");
}

function CreateUserForm({ accounts }: { readonly accounts: readonly PortalAccount[] }) {
  const create = useCreateUser();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [role, setRole] = useState<UserRole>("operator");
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  function toggle(accountId: string) {
    setSelected((current) =>
      current.includes(accountId)
        ? current.filter((id) => id !== accountId)
        : [...current, accountId],
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (create.isPending) return;
    setCreated(null);
    if (password !== confirm) {
      setError(MISMATCH);
      setPassword("");
      setConfirm("");
      return;
    }
    setError(null);
    const submitted = username;
    create.mutate(
      { username, password, role, accountIds: selected },
      {
        onSuccess: () => {
          setUsername("");
          setSelected([]);
          setCreated(`Utilisateur « ${submitted} » créé.`);
        },
        onError: (caught) => setError(errorOf(caught).message),
        // A submitted password is never kept in the form, whatever happened.
        onSettled: () => {
          setPassword("");
          setConfirm("");
        },
      },
    );
  }

  return (
    <form className="u-stack-4" onSubmit={onSubmit} aria-label="Créer un utilisateur">
      <div className={styles.field}>
        <label htmlFor="new-user-name">Nom d'utilisateur</label>
        <input
          id="new-user-name"
          className={styles.input}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor="new-user-password">Mot de passe</label>
        <input
          id="new-user-password"
          className={styles.input}
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor="new-user-confirm">Confirmer le mot de passe</label>
        <input
          id="new-user-confirm"
          className={styles.input}
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor="new-user-role">Rôle</label>
        <select
          id="new-user-role"
          className={styles.input}
          value={role}
          onChange={(e) => setRole(e.target.value as UserRole)}
        >
          {ROLE_ORDER.map((value) => (
            <option key={value} value={value}>
              {ROLE_LABELS[value]}
            </option>
          ))}
        </select>
      </div>
      <fieldset className={styles.fieldset}>
        <legend>Comptes portail accessibles</legend>
        {accounts.map((account) => (
          <label key={account.accountId} className={styles.check}>
            <input
              type="checkbox"
              checked={selected.includes(account.accountId)}
              onChange={() => toggle(account.accountId)}
            />
            {account.label}
          </label>
        ))}
      </fieldset>
      {error === null ? null : (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {created === null ? null : <p role="status">{created}</p>}
      <Button type="submit" variant="primary" disabled={create.isPending}>
        Créer l'utilisateur
      </Button>
    </form>
  );
}

interface UserRowProps {
  readonly user: PlatformUser;
  readonly accounts: readonly PortalAccount[];
  readonly onError: (message: string | null) => void;
}

function UserRow({ user, accounts, onError }: UserRowProps) {
  const update = useUpdateUser();
  const [resetting, setResetting] = useState(false);

  function toggleActive() {
    if (update.isPending) return;
    onError(null);
    update.mutate(
      { userId: user.userId, patch: { active: !user.active } },
      { onError: (caught) => onError(errorOf(caught).message) },
    );
  }

  return (
    <li className={styles.row}>
      <div className={styles.rowHead}>
        <span className={styles.username}>{user.username}</span>
        <span>{roleLabel(user.role)}</span>
        <span>{user.active ? "Actif" : "Désactivé"}</span>
        <span className="t-secondary">Comptes : {accountLabels(user.accountIds, accounts)}</span>
      </div>
      <div className={styles.actions}>
        <Button
          onClick={toggleActive}
          disabled={update.isPending}
          aria-label={`${user.active ? "Désactiver" : "Réactiver"} ${user.username}`}
        >
          {user.active ? "Désactiver" : "Réactiver"}
        </Button>
        <Button
          onClick={() => setResetting((open) => !open)}
          aria-expanded={resetting}
          aria-label={`Réinitialiser le mot de passe de ${user.username}`}
        >
          Réinitialiser le mot de passe
        </Button>
      </div>
      {resetting ? <ResetPasswordForm user={user} /> : null}
    </li>
  );
}

function ResetPasswordForm({ user }: { readonly user: PlatformUser }) {
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (reset.isPending) return;
    setDone(false);
    if (password !== confirm) {
      setError(MISMATCH);
      setPassword("");
      setConfirm("");
      return;
    }
    setError(null);
    reset.mutate(
      { userId: user.userId, password },
      {
        onSuccess: () => {
          setDone(true);
        },
        onError: (caught) => setError(errorOf(caught).message),
        onSettled: () => {
          setPassword("");
          setConfirm("");
        },
      },
    );
  }

  return (
    <form
      className={styles.resetForm}
      onSubmit={onSubmit}
      aria-label={`Réinitialiser le mot de passe de ${user.username}`}
    >
      <div className={styles.field}>
        <label htmlFor={`reset-${user.userId}`}>Nouveau mot de passe ({user.username})</label>
        <input
          id={`reset-${user.userId}`}
          className={styles.input}
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor={`reset-confirm-${user.userId}`}>
          Confirmer le nouveau mot de passe ({user.username})
        </label>
        <input
          id={`reset-confirm-${user.userId}`}
          className={styles.input}
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </div>
      {error === null ? null : (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {done ? <p role="status">Mot de passe réinitialisé.</p> : null}
      <Button type="submit" variant="primary" disabled={reset.isPending}>
        Enregistrer le mot de passe
      </Button>
    </form>
  );
}
