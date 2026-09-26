# Expanded science-image LoRA campaign — 2026-09-26 UTC

## Outcome

`TRAINING_COMPLETE / PAIRED_EVALUATION_PASS / PRODUCTION_ACTIVATION_NOT_AUTHORIZED`

The expanded internal science-assessment campaign completed one bounded SSD-1B LoRA run and a
four-case BASE-versus-ADAPTER holdout evaluation. The immutable training and evaluation file sets
are now published by the Orchestrator. Three holdout cases show a clear prompt/style improvement;
one is comparable to the base output; none shows a blocking regression. A third correction run was
therefore skipped to avoid overfitting the small corpus.

This closes the training campaign. It does **not** activate the adapter. The released training
contract deliberately records `state=EVALUATION_ONLY` and `activation_policy=FORBIDDEN`, while the
current production provider binding has no adapter pointer. Production activation needs a separate
protocol-first successor binding and rollback canary; copying the workspace weights into the live
provider is prohibited.

## Dataset and training evidence

- source campaign: `imgsciviscampaign_b9d83e3f8d66284eaf44d5595e47e847`;
- crop set: `imgsciviscampaigncropset_ede355b7331362c4bfd5644625d6a15f`;
- crop-set Artifact Revision: `rev_3e119d8935d14e388f89296d1dbb0eec`;
- crop-set semantic SHA-256:
  `sha256:9e5f740d9b3a2d8174302e7528f52c94cf577eab645124916e4e8b06c4dafa2a`;
- partition: 16 TRAIN, 4 VALIDATION, 4 HOLDOUT; 24 distinct reviewed members;
- direct/refined materializations: 5 / 19;
- probe plan: `imgscicampaignmicroprobe_e4cb8c79987162a90b5448df074b4894`;
- training run: `imgscicampaignmicrotrainrun_dbf6a066e2cce318733c1640e9056a6c`;
- realized training samples / optimizer steps: 16 / 200;
- final loss: `0.008189254440367222`;
- training result semantic SHA-256:
  `sha256:a75af2404a30f94e8d7faf23e6a314a7a03a1a57735eb835b102db198fcdf251`;
- adapter: `imgadapter_ddbbf983203c84edd8b231c5822dcafb` / revision
  `imgadapterrev_06803dcac6d52304426d9d542ad6d10d`;
- adapter manifest SHA-256:
  `sha256:be55afb0ec32d55b7768f37de6291e8c55b84f3b2e18c7aa109a3c01005d100d`.

Loss is a bounded training diagnostic, not an image-quality acceptance metric.

## Immutable publication evidence

Training output publication:

- result Artifact: `artifact_b2b676ce049d41f2a638d899f8d53ea2`;
- result Artifact Revision: `rev_4a0ac15a79ad4f22bc6d3e14ed85e941`;
- result member SHA-256:
  `sha256:7b7ee005cb26b2a941a0d964bb4c086731faaf634aa6705e9ddf7e8f1b810e57`;
- file-set manifest SHA-256:
  `sha256:a17c5519777b02bbd5cfa38f448f1865014dc5ade51db18a076a9f8f83ddaeb3`.

Paired evaluation publication:

- evaluation run: `imgscicampaignmicroevalrun_c25b26d6b32fcdabdd994305b8ee93aa`;
- result semantic SHA-256:
  `sha256:c7b33acda49a644f6c25acfb410916a74ff739f3593d29ba7e43ed6af8f86731`;
- result Artifact: `artifact_79a73805a16846f7be3290927acd294a`;
- result Artifact Revision: `rev_67130faa6af24fa7aeaede2e57c53800`;
- result member SHA-256:
  `sha256:e5b7a391de0245c38cc9114d7b24deb05c5d882cbd804ff46370239133e0e25d`;
- file-set manifest SHA-256:
  `sha256:462adb37c41b1a657f180dec59bd11b0f94726e7bfec82ca134b096b3599064a`;
- exact coverage: four HOLDOUT samples × BASE/ADAPTER = eight 800×500 PNGs.

The publication audit resolved both exact Artifact pointers, revalidated JSON Schema 2020-12 and
Pydantic values, checked training/evaluation hash linkage, and found exactly two `SUCCEEDED`
publication jobs. Workers never received PostgreSQL or NAS access.

## Visual review

All pairs use the same case prompt, negative prompt, seed, base-model revision, scheduler,
dimensions, inference steps, and guidance. The observed comparison is:

| Case | Subject | Decision | Finding |
| --- | --- | --- | --- |
| A | clustered mussel shells | ADAPTER_BETTER | adapter follows the requested clustered shell subject; base resembles unrelated seed forms |
| B | Mars surface | COMPARABLE | both are usable; adapter is slightly more stylized but has no blocking defect |
| C | tapered fossil shell | ADAPTER_BETTER | adapter produces geological fossil material and removes the first probe's tree-ring regression |
| D | folded rock | ADAPTER_BETTER | adapter is materially more photographic and geological than the stylized base output |

This review is an engineering visual audit, not a human production approval. The source, BASE, and
ADAPTER materializations remain available as bounded local review copies and the canonical eight
outputs are the evaluation Artifact members.

## Final gate and rollback

- correction training: `SKIPPED_NOT_JUSTIFIED_BY_HOLDOUT`;
- adapter training status: `COMPLETE`;
- durable publication: `PASS`;
- paired holdout integrity: `PASS`;
- production provider activation: `NOT_PERFORMED`;
- current rollback position: unchanged base-only immutable provider binding;
- future activation prerequisite: successor provider-binding JSON Schema/Pydantic contract that
  pins this adapter Artifact/Revision/member hashes, stages weights outside the worker, performs a
  bounded live canary, and can atomically restore the prior binding.

The first 15-member micro-probe remains historical evidence. Its dataset and negative activation
decision are not rewritten by this successor campaign.
