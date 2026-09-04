# Migrations live in `supabase/migrations/`

`PROJECT_STRUCTURE.md §2` specifies a top-level `migrations/` directory, but the
Supabase CLI requires migrations under `supabase/migrations/` and will not discover
them anywhere else.

**Resolution:** `supabase/migrations/` is canonical. This directory exists only to
point there, so the repository does not silently contradict the spec.

Recorded per `FINAL_SPECIFICATION §37`; `PROJECT_STRUCTURE.md` is updated to match.

```bash
supabase migration new <name>   # create
supabase db reset               # rebuild local DB from scratch + seed
supabase db push                # apply to the linked project
```

