/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, onMounted, onWillUnmount, xml } from "@odoo/owl";

export class ExamCountdownTimer extends Component {
    static template = xml`
        <div class="d-inline-flex align-items-center gap-2 px-3 py-2 rounded-3 shadow-sm border" t-att-class="containerClass">
            <i class="fa fa-clock-o fa-lg" t-att-class="iconClass"/>
            <div class="d-flex flex-column text-start">
                <span class="small fw-semibold text-uppercase" style="font-size: 0.72rem; letter-spacing: 0.5px;">
                    <t t-esc="label"/>
                </span>
                <span class="fs-4 fw-bold font-monospace" style="line-height: 1.1;">
                    <t t-esc="displayTime"/>
                </span>
            </div>
        </div>
    `;

    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.state = useState({
            remainingSeconds: 0,
            hasExpired: false,
        });
        this.interval = null;

        onMounted(() => {
            this.updateRemaining();
            this.interval = setInterval(() => {
                this.tick();
            }, 1000);
        });

        onWillUnmount(() => {
            if (this.interval) {
                clearInterval(this.interval);
            }
        });
    }

    get deadlineMs() {
        const val = this.props.record.data[this.props.name];
        if (!val) return null;
        if (typeof val === "object" && typeof val.toMillis === "function") {
            return val.toMillis();
        }
        if (typeof val === "string") {
            return new Date(val).getTime();
        }
        return null;
    }

    get status() {
        return this.props.record.data.status;
    }

    updateRemaining() {
        if (this.status !== "InProgress" || !this.deadlineMs) {
            this.state.remainingSeconds = 0;
            return;
        }
        const now = Date.now();
        const diffMs = this.deadlineMs - now;
        const diffSec = Math.max(0, Math.floor(diffMs / 1000));
        this.state.remainingSeconds = diffSec;
        if (diffSec <= 0 && !this.state.hasExpired) {
            this.handleExpire();
        }
    }

    tick() {
        if (this.status !== "InProgress" || !this.deadlineMs) return;
        if (this.state.remainingSeconds > 0) {
            this.state.remainingSeconds -= 1;
            if (this.state.remainingSeconds <= 0 && !this.state.hasExpired) {
                this.handleExpire();
            }
        }
    }

    handleExpire() {
        this.state.hasExpired = true;
        this.state.remainingSeconds = 0;
        // Tự động nhấn nút nộp bài để lưu bài và chấm điểm
        setTimeout(() => {
            const submitBtn = document.querySelector('button[name="action_submit_exam"]');
            if (submitBtn) {
                submitBtn.click();
            }
        }, 500);
    }

    get displayTime() {
        if (this.status === "NotStarted") {
            const mins = this.props.record.data.time_limit_minutes || 15;
            return String(mins).padStart(2, '0') + ":00";
        }
        if (this.status !== "InProgress") {
            return "00:00";
        }
        const sec = this.state.remainingSeconds;
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return String(m).padStart(2, '0') + ":" + String(s).padStart(2, '0');
    }

    get label() {
        if (this.status === "NotStarted") return "Thời Gian Làm Bài";
        if (this.status === "InProgress") {
            if (this.state.remainingSeconds <= 120) return "Sắp Hết Giờ!";
            return "Thời Gian Còn Lại";
        }
        return "Đã Hoàn Thành";
    }

    get containerClass() {
        if (this.status === "NotStarted") {
            return "bg-light text-secondary border-secondary-subtle";
        }
        if (this.status === "InProgress") {
            if (this.state.remainingSeconds <= 120) {
                return "bg-danger-subtle text-danger border-danger";
            }
            if (this.state.remainingSeconds <= 300) {
                return "bg-warning-subtle text-warning-emphasis border-warning";
            }
            return "bg-success-subtle text-success border-success";
        }
        return "bg-secondary-subtle text-secondary border-secondary";
    }

    get iconClass() {
        if (this.status === "InProgress" && this.state.remainingSeconds <= 120) {
            return "text-danger fa-spin";
        }
        return "";
    }
}

export const examCountdownTimer = {
    component: ExamCountdownTimer,
    supportedTypes: ["datetime"],
};

registry.category("fields").add("exam_countdown_timer", examCountdownTimer);
