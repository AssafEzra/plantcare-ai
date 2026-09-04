-- =============================================================================
-- 0003 · Storage: the plant-images bucket and its access policies.
--
-- Spec: FINAL_SPECIFICATION §20 (images and storage), §26 (owner-only access)
--       DATABASE_SCHEMA "RLS model" (storage policies enforce owner access for
--       visible images and Admin-only access to retained hidden AI-history images)
--
-- Created as a migration rather than by hand in the dashboard so PROD gets an
-- identical bucket with identical policies, and so the configuration is
-- reviewable (SETUP §7: never make undocumented manual changes).
--
-- Object key layout inside the bucket:
--     {user_id}/{plant_id}/{gallery|identification|health}/{filename}
-- so (storage.foldername(name))[1] is always the owning user's id. Every policy
-- below keys on that segment.
-- =============================================================================

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'plant-images',
  'plant-images',
  false,                       -- private: reads go through short-lived signed URLs
  10485760,                    -- 10 MB per image (FINAL §20)
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update
  set public             = excluded.public,
      file_size_limit    = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- The MIME allow-list is defence in depth, not the primary gate: the application
-- validates by decoding the image with Pillow, because a client-supplied
-- content-type is trivially forged.

-- -----------------------------------------------------------------------------
-- Policies on storage.objects, scoped to this bucket only.
-- -----------------------------------------------------------------------------

create policy plant_images_select_own
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'plant-images'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy plant_images_insert_own
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'plant-images'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy plant_images_update_own
  on storage.objects for update
  to authenticated
  using (
    bucket_id = 'plant-images'
    and (storage.foldername(name))[1] = auth.uid()::text
  )
  with check (
    bucket_id = 'plant-images'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- Deletion is permitted at the storage layer, but the application only calls it
-- for images never used by AI. FINAL §20 requires AI-used images to be retained
-- for history/audit and merely hidden from the user; that rule lives in the
-- image service, which flips plant_images.user_visible instead of deleting.
create policy plant_images_delete_own
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'plant-images'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- Admins may read retained AI-used images that are hidden from their owner
-- (FINAL §20 retention, §29 admin access). Read-only on purpose: an admin has no
-- reason to write into a user's image namespace.
create policy plant_images_select_admin
  on storage.objects for select
  to authenticated
  using (bucket_id = 'plant-images' and public.is_admin());
