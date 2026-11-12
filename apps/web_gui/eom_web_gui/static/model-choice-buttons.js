// The existing select retains the validated form value. Buttons only present its choices.
const groups = new WeakMap();
export function modelChoiceButtons(select, label, discovered = []) {
  let group = groups.get(select);
  if (!group) {
    group = select.ownerDocument.createElement("div");
    group.className = "model-choice-buttons";
    group.setAttribute("role", "group");
    select.after(group);
    select.hidden = true;
    groups.set(select, group);
  }
  group.setAttribute("aria-label", label);
  const choices = new Map(Array.from(select.options).filter(option => option.value)
    .map(option => [option.value, {value: option.value, label: option.textContent, admitted: true}]));
  for (const choice of discovered) if (!choices.has(choice.value)) choices.set(choice.value, choice);
  const focusedValue = group.contains(select.ownerDocument.activeElement)
    ? select.ownerDocument.activeElement.dataset.choiceValue : null;
  group.replaceChildren();
  for (const choice of choices.values()) {
    const button = select.ownerDocument.createElement("button");
    button.type = "button";
    button.className = "model-choice";
    button.dataset.choiceValue = choice.value;
    button.textContent = choice.label;
    button.setAttribute("aria-pressed", String(select.value === choice.value));
    button.disabled = select.disabled || !choice.admitted;
    if (!choice.admitted) {
      const status = select.ownerDocument.createElement("span");
      status.className = "model-choice-state";
      status.textContent = choice.reason || "실행 검증 필요";
      button.append(status);
      button.title = choice.reason || "계정에서 조회되었지만 이 작업의 실행 검증은 아직 없습니다.";
    }
    button.addEventListener("click", () => {
      if (select.disabled || button.disabled || select.value === choice.value) return;
      select.value = choice.value;
      select.dispatchEvent(new Event("change", {bubbles: true}));
    });
    group.append(button);
    if (choice.value === focusedValue && !button.disabled) button.focus();
  }
  if (!choices.size || !select.value) {
    const message = select.ownerDocument.createElement("span");
    message.className = "model-choice-empty";
    message.textContent = select.selectedOptions[0]?.textContent || "모델 목록 확인 필요";
    group.append(message);
  }
}

export function discoveredModelChoices(catalog) {
  return catalog.map(model => ({value: model.model, label: model.model, admitted: false}));
}

export function discoveredEffortChoices(catalog, model, labels) {
  return (catalog.find(value => value.model === model)?.efforts || []).map(effort => ({
    value: effort, label: labels[effort] || effort, admitted: false,
    reason: labels[effort] ? "실행 검증 필요" : "현재 실행 규약 미지원",
  }));
}
