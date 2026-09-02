import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import {
  INotebookTracker,
  type NotebookPanel
} from '@jupyterlab/notebook';

import {
  applyNotebookCodeCellAction,
  type BridgeCell,
  type NewCodeCell,
  type NotebookBridgeModel,
  type NotebookCodeCellAction
} from './notebook_action.js';


export const APPLY_NOTEBOOK_ACTION_COMMAND =
  'kcs-mcp:apply-notebook-code-cell-action';


function createBridgeModel(panel: NotebookPanel): NotebookBridgeModel {
  const notebook = panel.content;
  const model = notebook.model;

  if (!model) {
    throw new Error('활성 Notebook model이 준비되지 않았습니다.');
  }

  return {
    get path(): string {
      return panel.context.path;
    },

    get readOnly(): boolean {
      return model.readOnly;
    },

    get activeCellIndex(): number {
      return notebook.activeCellIndex;
    },

    get cells(): readonly BridgeCell[] {
      const cells: BridgeCell[] = [];

      for (let index = 0; index < model.cells.length; index += 1) {
        const cell = model.cells.get(index);

        cells.push({
          id: cell.id,
          type: cell.type,
          getSource: () => cell.sharedModel.getSource(),
          setSource: source => cell.sharedModel.setSource(source),
          setMetadata: metadata => {
            for (const [key, value] of Object.entries(metadata)) {
              if (value !== undefined) {
                cell.setMetadata(key, value);
              }
            }
          }
        });
      }

      return cells;
    },

    transact(change: () => void): void {
      model.sharedModel.transact(change);
    },

    insertCodeCell(index: number, cell: NewCodeCell): void {
      model.sharedModel.insertCell(index, cell);
    },

    setActiveCellIndex(index: number): void {
      notebook.activeCellIndex = index;
    },

    save(): Promise<void> {
      return panel.context.save();
    },

    undo(): void {
      model.sharedModel.undo();
    }
  };
}


const plugin: JupyterFrontEndPlugin<void> = {
  id: '@kcs-mcp/jupyterlab-bridge:plugin',
  autoStart: true,
  requires: [INotebookTracker],
  activate: (
    app: JupyterFrontEnd,
    tracker: INotebookTracker
  ): void => {
    app.commands.addCommand(
      APPLY_NOTEBOOK_ACTION_COMMAND,
      {
        label: 'Apply KCS MCP Notebook Code Cell Action',
        execute: async args => {
          const panel = tracker.currentWidget;

          if (!panel) {
            throw new Error('활성 Notebook이 없습니다.');
          }

          const action = args.action as unknown as NotebookCodeCellAction;

          if (!action) {
            throw new Error('Notebook action이 필요합니다.');
          }

          return applyNotebookCodeCellAction(
            createBridgeModel(panel),
            action
          );
        }
      }
    );
  }
};


export default plugin;
