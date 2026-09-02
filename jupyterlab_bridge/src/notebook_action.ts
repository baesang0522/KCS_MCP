import type { ICodeCell } from '@jupyterlab/nbformat';


export type NotebookCellMode = 'revise' | 'create';
export type CellMetadata = ICodeCell['metadata'];

export interface NotebookCodeCellAction {
  action_id: string;
  type: 'write_jupyter_code_cell';
  task_id: string;
  notebook_path: string;
  mode: NotebookCellMode;
  source: string;
  target_cell_id: string | null;
  expected_source_hash: string | null;
}

export interface BridgeCell {
  readonly id: string;
  readonly type: string;
  getSource(): string;
  setSource(source: string): void;
  setMetadata(metadata: CellMetadata): void;
}

export interface NewCodeCell extends ICodeCell {
  cell_type: 'code';
  id: string;
  source: string;
  metadata: CellMetadata;
  execution_count: null;
  outputs: [];
}

export interface NotebookBridgeModel {
  readonly path: string;
  readonly readOnly: boolean;
  readonly cells: readonly BridgeCell[];
  readonly activeCellIndex: number;
  transact(change: () => void): void;
  insertCodeCell(index: number, cell: NewCodeCell): void;
  setActiveCellIndex(index: number): void;
  save(): Promise<void>;
  undo(): void;
}

export interface NotebookCellResult {
  notebook_path: string;
  operation:
    | 'revision_cell_inserted'
    | 'active_empty_code_cell_filled'
    | 'creation_cell_inserted';
  cell_id: string;
  anchor_cell_id: string | null;
  executed: false;
}

function normalizePath(path: string): string {
  return path.replaceAll('\\', '/').replace(/^\/+/, '');
}

function validateAction(action: NotebookCodeCellAction): void {
  if (action.type !== 'write_jupyter_code_cell') {
    throw new Error('지원하지 않는 Notebook action입니다.');
  }

  if (!action.action_id || !action.task_id) {
    throw new Error('action_id와 task_id가 필요합니다.');
  }

  if (!action.notebook_path.toLowerCase().endsWith('.ipynb')) {
    throw new Error('.ipynb Notebook action만 적용할 수 있습니다.');
  }

  if (action.mode !== 'revise' && action.mode !== 'create') {
    throw new Error("mode는 'revise' 또는 'create'여야 합니다.");
  }

  if (!action.source.trim()) {
    throw new Error('source는 비어 있을 수 없습니다.');
  }

  if (action.mode === 'revise' && !action.target_cell_id) {
    throw new Error('revise mode에는 target_cell_id가 필요합니다.');
  }

  if (action.mode === 'create' && action.target_cell_id !== null) {
    throw new Error('create mode에는 target_cell_id를 사용할 수 없습니다.');
  }

  if (
    action.expected_source_hash !== null &&
    !/^[0-9a-f]{64}$/i.test(action.expected_source_hash)
  ) {
    throw new Error('expected_source_hash는 SHA-256 hex여야 합니다.');
  }
}

export async function sha256Source(source: string): Promise<string> {
  const bytes = new TextEncoder().encode(source);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);

  return Array.from(new Uint8Array(digest))
    .map(value => value.toString(16).padStart(2, '0'))
    .join('');
}

function createCellId(cells: readonly BridgeCell[]): string {
  const existingIds = new Set(cells.map(cell => cell.id));

  while (true) {
    const cellId = globalThis.crypto.randomUUID();

    if (!existingIds.has(cellId)) {
      return cellId;
    }
  }
}

function createMetadata(
  action: NotebookCodeCellAction,
  anchorCellId: string | null
): CellMetadata {
  return {
    task_id: action.task_id,
    operation: action.mode,
    anchor_cell_id: anchorCellId,
    created_at: new Date().toISOString()
  };
}

function createCodeCell(
  action: NotebookCodeCellAction,
  cells: readonly BridgeCell[],
  anchorCellId: string | null
): NewCodeCell {
  return {
    cell_type: 'code',
    id: createCellId(cells),
    source: action.source,
    metadata: createMetadata(action, anchorCellId),
    execution_count: null,
    outputs: []
  };
}

export async function applyNotebookCodeCellAction(
  notebook: NotebookBridgeModel,
  action: NotebookCodeCellAction
): Promise<NotebookCellResult> {
  validateAction(action);

  if (notebook.readOnly) {
    throw new Error('읽기 전용 Notebook은 수정할 수 없습니다.');
  }

  if (
    normalizePath(notebook.path) !==
    normalizePath(action.notebook_path)
  ) {
    throw new Error('활성 Notebook과 action의 경로가 다릅니다.');
  }

  let operation: NotebookCellResult['operation'];
  let cellId: string;
  let anchorCellId: string | null;
  let activeIndexAfterChange: number;
  const activeIndexBeforeChange = notebook.activeCellIndex;

  if (action.mode === 'revise') {
    const targetIndex = notebook.cells.findIndex(
      cell => cell.id === action.target_cell_id
    );

    if (targetIndex === -1) {
      throw new Error('target_cell_id에 해당하는 셀이 없습니다.');
    }

    const targetCell = notebook.cells[targetIndex];

    if (targetCell.type !== 'code') {
      throw new Error('revise 대상은 code cell이어야 합니다.');
    }

    const targetSource = targetCell.getSource();

    if (action.expected_source_hash !== null) {
      const currentHash = await sha256Source(targetSource);

      if (currentHash !== action.expected_source_hash.toLowerCase()) {
        throw new Error('대상 셀 source hash가 일치하지 않습니다.');
      }
    }

    const newCell = createCodeCell(
      action,
      notebook.cells,
      targetCell.id
    );

    notebook.transact(() => {
      const currentIndex = notebook.cells.findIndex(
        cell => cell.id === action.target_cell_id
      );
      const currentTarget = notebook.cells[currentIndex];

      if (
        currentIndex !== targetIndex ||
        !currentTarget ||
        currentTarget.type !== 'code' ||
        currentTarget.getSource() !== targetSource
      ) {
        throw new Error('대상 셀이 action 검증 후 변경되었습니다.');
      }

      notebook.insertCodeCell(targetIndex + 1, newCell);
    });

    operation = 'revision_cell_inserted';
    cellId = newCell.id;
    anchorCellId = targetCell.id;
    activeIndexAfterChange = targetIndex + 1;
  } else {
    const activeIndex = notebook.activeCellIndex;
    const activeCell =
      activeIndex >= 0 && activeIndex < notebook.cells.length
        ? notebook.cells[activeIndex]
        : null;

    if (
      activeCell !== null &&
      activeCell.type === 'code' &&
      activeCell.getSource().trim() === ''
    ) {
      const emptySource = activeCell.getSource();
      const metadata = createMetadata(action, activeCell.id);

      notebook.transact(() => {
        const currentCell = notebook.cells[activeIndex];

        if (
          !currentCell ||
          currentCell.id !== activeCell.id ||
          currentCell.type !== 'code' ||
          currentCell.getSource() !== emptySource
        ) {
          throw new Error('활성 셀이 action 검증 후 변경되었습니다.');
        }

        currentCell.setSource(action.source);
        currentCell.setMetadata(metadata);
      });

      operation = 'active_empty_code_cell_filled';
      cellId = activeCell.id;
      anchorCellId = activeCell.id;
      activeIndexAfterChange = activeIndex;
    } else {
      const insertIndex = activeCell === null ? 0 : activeIndex + 1;
      const anchorId = activeCell?.id ?? null;
      const newCell = createCodeCell(
        action,
        notebook.cells,
        anchorId
      );

      notebook.transact(() => {
        const currentActive =
          activeIndex >= 0 && activeIndex < notebook.cells.length
            ? notebook.cells[activeIndex]
            : null;

        if (
          (activeCell === null && currentActive !== null) ||
          (activeCell !== null && currentActive?.id !== activeCell.id)
        ) {
          throw new Error('활성 셀이 action 검증 후 변경되었습니다.');
        }

        notebook.insertCodeCell(insertIndex, newCell);
      });

      operation = 'creation_cell_inserted';
      cellId = newCell.id;
      anchorCellId = anchorId;
      activeIndexAfterChange = insertIndex;
    }
  }

  notebook.setActiveCellIndex(activeIndexAfterChange);

  try {
    await notebook.save();
  } catch (error) {
    notebook.undo();
    notebook.setActiveCellIndex(activeIndexBeforeChange);
    throw error;
  }

  return {
    notebook_path: action.notebook_path,
    operation,
    cell_id: cellId,
    anchor_cell_id: anchorCellId,
    executed: false
  };
}
