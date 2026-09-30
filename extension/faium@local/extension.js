import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const STATE_FILE = GLib.build_filenamev([GLib.get_user_state_dir(), 'ai-agent-usage.json']);
const REFRESH_SECONDS = 30;

const FAIUMIndicator = GObject.registerClass(
class FAIUMIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'FAIUM');

        this._label = new St.Label({
            text: 'AI --',
            style_class: 'faium-panel-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._label);

        this._summary = new PopupMenu.PopupMenuItem('Waiting for usage data', {reactive: false});
        this._updated = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._agentsSection = new PopupMenu.PopupMenuSection();

        this.menu.addMenuItem(this._summary);
        this.menu.addMenuItem(this._updated);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addMenuItem(this._agentsSection);

        this._monitor = null;
        this._timerId = 0;
        this._startStateWatch();
        this._refresh();
    }

    destroy() {
        if (this._timerId) {
            GLib.Source.remove(this._timerId);
            this._timerId = 0;
        }

        if (this._monitor) {
            this._monitor.cancel();
            this._monitor = null;
        }

        super.destroy();
    }

    _startStateWatch() {
        this._timerId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            REFRESH_SECONDS,
            () => {
                this._refresh();
                return GLib.SOURCE_CONTINUE;
            }
        );

        const file = Gio.File.new_for_path(STATE_FILE);
        try {
            this._monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._monitor.connect('changed', () => this._refresh());
        } catch (error) {
            log(`FAIUM: unable to monitor ${STATE_FILE}: ${error.message}`);
        }
    }

    _refresh() {
        let state = null;
        try {
            const [ok, contents] = Gio.File.new_for_path(STATE_FILE).load_contents(null);
            if (ok) {
                state = JSON.parse(new TextDecoder().decode(contents));
            }
        } catch (error) {
            this._renderMissingState();
            return;
        }

        this._renderState(state);
    }

    _renderMissingState() {
        this._label.text = 'AI --';
        this._summary.label.text = `No state file at ${STATE_FILE}`;
        this._updated.label.text = 'Run: faium collect';
        this._agentsSection.removeAll();
    }

    _renderState(state) {
        const totals = state?.totals ?? {};
        const totalTokens = Number(totals.total_tokens ?? 0);
        const cost = Number(totals.cost_usd ?? 0);
        const costPrefix = totals.cost_estimated ? 'est. ' : '';
        const requests = Number(totals.requests ?? 0);

        this._label.text = `AI ${formatTokens(totalTokens)}`;
        this._summary.label.text = `${formatTokens(totalTokens)} tokens | ${requests} requests | ${costPrefix}$${cost.toFixed(4)}`;
        const windowLabel = state.window?.label ? ` | ${formatWindowLabel(state.window.label)}` : '';
        this._updated.label.text = state.generated_at
            ? `Updated ${formatTimestamp(state.generated_at)}${windowLabel}`
            : `Updated unknown${windowLabel}`;

        this._agentsSection.removeAll();
        const agents = Array.isArray(state.agents) ? state.agents : [];
        if (agents.length === 0) {
            this._agentsSection.addMenuItem(new PopupMenu.PopupMenuItem('No agent usage found', {reactive: false}));
            return;
        }

        for (const agent of agents) {
            const model = agent.active_model ?? agent.models?.[0] ?? 'unknown model';
            const text = `${agent.name}: ${formatTokens(agent.total_tokens ?? 0)} | ${model}`;
            this._agentsSection.addMenuItem(new PopupMenu.PopupMenuItem(text, {reactive: false}));
        }
    }
});

function formatTokens(value) {
    if (value >= 1000000) {
        return `${(value / 1000000).toFixed(1)}M`;
    }
    if (value >= 1000) {
        return `${(value / 1000).toFixed(1)}K`;
    }
    return `${value}`;
}

function formatTimestamp(value) {
    const timestamp = Date.parse(value);
    if (!Number.isFinite(timestamp)) {
        return value;
    }
    return new Date(timestamp).toLocaleString();
}

function formatWindowLabel(value) {
    if (value === 'month') {
        return 'calendar month';
    }
    if (value === 'all') {
        return 'all time';
    }
    return value;
}

export default class FAIUMExtension extends Extension {
    enable() {
        this._indicator = new FAIUMIndicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
