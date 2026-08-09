<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import {
  App,
  Button as AButton,
  Checkbox as ACheckbox,
  Input as AInput,
  Modal as AModal,
} from 'ant-design-vue'
import { describeApiError } from '../api/client'
import type { OwnerRef, WpOwner } from '../api/types'
import { useBoardContext, type OwnerPickerRequest } from '../runtime/context'

/**
 * Owner 셀 팝업 — `plan.md` §0.5.9.
 *
 * Two jobs in one window, and they are deliberately **not** the same job:
 *
 *  - **선택** (top): which owners this row has. Checking a box only changes the row in the
 *    store, so it becomes a dirty edit saved by the ordinary 저장 button. No request is made
 *    — the row's owners are board data, and board data saves through one path.
 *  - **관리** (list): add, rename, delete, reorder the scope's owner master. These *are*
 *    immediate API calls, because master data is not part of the board's save payload; there
 *    would be nothing to flush them with.
 *
 * Mixing the two in one window is what the user asked for, but the split above is why
 * [적용] closes with pending changes on the row and yet the renamed owner is already saved.
 *
 * Same shape as the Phase/Milestone 관리 팝업 (§0.4), and hosted the same way — at the shell,
 * not inside a cell editor, since an ag-grid popup editor is destroyed the moment editing
 * stops and would take the modal with it.
 *
 * **순서 개념이 없다** (`plan.md` §0.5.10 정밀화). 드래그 재정렬과 순서 열을 걷어냈다 — Owner
 * 는 문서와 달리 번호로 불리지 않으므로 순서를 보여주면 사용자가 관리해야 할 것이 하나 더
 * 늘어날 뿐이고, 실제로는 서버가 준 순서를 그대로 읽으면 된다. `sort_order` 는 여전히 서버가
 * 들고 있고 새 Owner 는 목록 끝에 붙는다.
 */
const props = defineProps<{ request: OwnerPickerRequest }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { api, board, master, notify, popupContainer } = useBoardContext()
const { modal } = App.useApp()

const item = computed(() => board.items.value.find((row) => row.id === props.request.itemId))

/**
 * `board.readOnly` — so a PUBLISHED/ARCHIVED version is view-only here too (§0.5.9).
 *
 * Stricter than the retired Owner 탭, which gated owner editing on `hostReadOnly` alone on
 * the grounds that owners are not version-scoped. This window is opened *from a board cell*,
 * so it inherits that board's editability; a locked board offering owner management would be
 * a write action reached from a read-only screen. That difference is why the tab's removal
 * (§0.5.9) is not a pure deletion — this is now the only owner editor, under the tighter gate.
 */
const editable = computed(() => !board.readOnly.value)

const owners = computed(() => master.owners.value)

/** Ids checked in the picker. Seeded from the row, then purely local until [적용]. */
const selected = ref<Set<number>>(new Set((item.value?.owners ?? []).map((o) => o.id)))

const busy = ref(false)
/**
 * Owner id currently being renamed, and the draft.
 *
 * `'new'` is the row the [Owner 추가] button just appended — it has no id yet and is created
 * on commit. Editing an existing name and naming a new one are the same gesture, which is the
 * point of §0.5.10's "다른 팝업들과 동일하게": the other popups add an inline row too, and a
 * separate name field beside the table was the odd one out.
 */
const renamingId = ref<number | 'new' | null>(null)
const renameDraft = ref('')

function toggle(id: number, checked: boolean) {
  const next = new Set(selected.value)
  if (checked) next.add(id)
  else next.delete(id)
  selected.value = next
}

/** [적용] — row-local, no request. Saved later by the board's own 저장. */
function apply() {
  const row = item.value
  if (!row || !editable.value) return emit('close')
  const picked: OwnerRef[] = owners.value
    .filter((o) => selected.value.has(o.id))
    .map((o) => ({ id: o.id, name: o.name }))
  board.patchItem(row.id, { owners: picked })
  emit('close')
}

async function refresh() {
  const scope = board.scope.value
  if (scope) await master.loadForScope(scope)
}

async function run(action: () => Promise<unknown>, failure: string) {
  const scope = board.scope.value
  if (!scope || !editable.value) return
  busy.value = true
  try {
    await action()
    await refresh()
  } catch (error) {
    notify.error(failure, describeApiError(error, ''))
  } finally {
    busy.value = false
  }
}

/**
 * Commit-on-blur, deferred by a tick.
 *
 * Committing synchronously unmounts the `<a-input>` from inside antd's own blur handler,
 * which then dereferences its now-null internal ref and throws. Waiting one tick lets antd
 * finish before the row disappears. (Found by `check:dom` — the run died on
 * `inputRef.value.input` rather than failing an assertion.)
 */
const deferCommit = (commit: () => void) => void nextTick(commit)

/** [Owner 추가] — appends an empty inline row; nothing is sent until it is named. */
function addOwner() {
  if (!editable.value) return
  renamingId.value = 'new'
  renameDraft.value = ''
}

function startRename(owner: WpOwner) {
  if (!editable.value) return
  renamingId.value = owner.id
  renameDraft.value = owner.name
}

function cancelRename() {
  renamingId.value = null
  renameDraft.value = ''
}

/** Commit — creates when the row is the pending new one, renames otherwise. */
async function commitNew() {
  if (renamingId.value !== 'new') return
  const name = renameDraft.value.trim()
  renamingId.value = null
  renameDraft.value = ''
  if (!name) return
  if (owners.value.some((o) => o.name === name)) return notify.warn('같은 이름이 이미 있습니다.')
  const scope = board.scope.value!
  await run(
    () => api.createOwner(scope, { name, sort_order: owners.value.length + 1, is_active: true }),
    'Owner 추가에 실패했습니다.',
  )
}

async function commitRename(owner: WpOwner) {
  if (renamingId.value !== owner.id) return
  const name = renameDraft.value.trim()
  renamingId.value = null
  if (!name || name === owner.name) return
  const scope = board.scope.value!
  await run(() => api.updateOwner(scope, owner.id, { name }), 'Owner 이름 변경에 실패했습니다.')
}

/**
 * Delete, with §2.6's rule spelled out **before** the call.
 *
 * The usage count is only knowable from the response, so the confirm explains the rule and
 * the result reports the number. An owner in use is deactivated rather than removed.
 */
function removeOwner(owner: WpOwner) {
  if (!editable.value) return
  const scope = board.scope.value
  if (!scope) return
  modal.confirm({
    title: `'${owner.name}' 을(를) 삭제할까요?`,
    content:
      '이 Owner 를 참조하는 항목이 있으면 삭제 대신 비활성 처리되고, 사용 중인 항목 수를 알려드립니다.',
    okText: '삭제',
    okType: 'danger',
    cancelText: '취소',
    onOk: async () => {
      busy.value = true
      try {
        const result = await api.deleteOwner(scope, owner.id)
        await refresh()
        if (result.deleted) notify.success('삭제되었습니다.')
        else {
          notify.warn(
            result.message ?? `${result.usage_count}개 항목에서 사용 중이라 비활성 처리했습니다.`,
          )
        }
      } catch (error) {
        notify.error('삭제에 실패했습니다.', describeApiError(error, ''))
      } finally {
        busy.value = false
      }
    },
  })
}

</script>

<template>
  <AModal
    :open="true"
    title="Owner 선택 · 관리"
    :width="560"
    :get-container="popupContainer"
    :mask-closable="false"
    ok-text="적용"
    cancel-text="취소"
    :ok-button-props="{ disabled: !editable }"
    @ok="apply"
    @cancel="emit('close')"
  >
    <p class="wp-mb-2 wp-text-xs" style="color: #8c8c8c">
      체크한 Owner 가 이 행의 담당이 됩니다 — [적용] 은 화면에만 반영되고, 저장은 툴바의
      저장 버튼입니다. 아래 목록의 <b>추가·이름 변경·삭제·순서</b> 는 기준정보라 즉시 반영됩니다.
    </p>
    <p v-if="!editable" class="wp-mb-2 wp-text-xs" style="color: #d48806">
      읽기 전용입니다 — 열람만 가능합니다.
    </p>

    <table class="wp-w-full wp-text-[13px]" data-wp-owner-table>
      <thead>
        <tr style="color: #8c8c8c">
          <th class="wp-w-12 wp-py-1 wp-font-medium">선택</th>
          <th class="wp-py-1 wp-text-left wp-font-medium">이름</th>
          <th class="wp-w-24" />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="owner in owners"
          :key="owner.id"
          class="wp-border-0 wp-border-t wp-border-solid"
          data-wp-owner-row
          style="border-color: #f0f0f0"
        >
          <td class="wp-py-1 wp-text-center">
            <ACheckbox
              :checked="selected.has(owner.id)"
              :disabled="!editable"
              :data-wp-owner-pick="owner.id"
              @change="(e: { target: { checked: boolean } }) => toggle(owner.id, e.target.checked)"
            />
          </td>
          <td class="wp-py-1">
            <AInput
              v-if="renamingId === owner.id"
              v-model:value="renameDraft"
              size="small"
              :disabled="busy"
              @press-enter="commitRename(owner)"
              @blur="deferCommit(() => commitRename(owner))"
            />
            <span
              v-else
              data-wp-owner-name
              :class="editable ? 'wp-cursor-pointer' : ''"
              :style="{ color: owner.is_active ? '#0f172a' : '#bfbfbf' }"
              @click="startRename(owner)"
            >
              {{ owner.name }}<span v-if="!owner.is_active" class="wp-ml-1 wp-text-2xs">(비활성)</span>
            </span>
          </td>
          <td class="wp-py-1 wp-text-right">
            <AButton
              v-if="editable"
              size="small"
              type="link"
              danger
              data-wp-owner-delete
              :disabled="busy"
              @click="removeOwner(owner)"
            >
              삭제
            </AButton>
          </td>
        </tr>
        <!-- [Owner 추가] 가 만든 인라인 행 — 이름을 넣어야 생성된다. -->
        <tr v-if="renamingId === 'new'" class="wp-border-0 wp-border-t wp-border-solid" style="border-color: #f0f0f0">
          <td />
          <td class="wp-py-1">
            <AInput
              v-model:value="renameDraft"
              size="small"
              autofocus
              placeholder="새 Owner 이름"
              data-wp-owner-new
              :disabled="busy"
              @press-enter="commitNew"
              @blur="deferCommit(commitNew)"
              @keyup.esc="cancelRename"
            />
          </td>
          <td />
        </tr>
      </tbody>
    </table>

    <div v-if="editable" class="wp-mt-3">
      <AButton size="small" data-wp-owner-add :disabled="busy" @click="addOwner">
        ＋ Owner 추가
      </AButton>
    </div>
  </AModal>
</template>
