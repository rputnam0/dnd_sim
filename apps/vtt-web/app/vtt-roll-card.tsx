import type { VttRollCard } from "./vtt-roll-cards";

function titleCase(value: string): string {
  return value
    .replace(/^action:/, "")
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function outcome(card: VttRollCard): string {
  if (card.fact.kind === "damage") {
    const damageType = card.fact.damage_type ? ` ${card.fact.damage_type}` : "";
    return `${card.fact.applied_damage} applied${damageType} damage`;
  }
  if (card.fact.kind === "healing") {
    const overheal = card.fact.overheal ?? 0;
    return `${card.fact.effective_healing} effective healing${overheal > 0 ? ` · ${overheal} overheal` : ""}`;
  }
  return titleCase(card.fact.outcome);
}

export function VttRollCardArticle({
  card,
  source,
}: {
  card: VttRollCard;
  source: "preview" | "commit" | "stream";
}) {
  return (
    <article className={`roll-card roll-card-${card.fact.kind}`} aria-labelledby={`roll-title-${card.card_id}`}>
      <header>
        <div>
          <p className="eyebrow">{source === "preview" ? "Authoritative preview" : "Authoritative roll"}</p>
          <h3 id={`roll-title-${card.card_id}`}>
            {card.action_id ? titleCase(card.action_id) : titleCase(card.purpose)}
          </h3>
        </div>
        <strong className="roll-total" aria-label={`Total ${card.fact.total}`}>
          {card.fact.total}
        </strong>
      </header>
      <p className="roll-outcome">
        {card.fact.critical ? "Critical · " : ""}{outcome(card)}
      </p>
      <p className="roll-expression"><code>{card.fact.expression}</code></p>
      <details>
        <summary>Show generated dice</summary>
        {card.fact.faces.length > 0 ? (
          <ol className="roll-faces">
            {card.fact.faces.map((face) => (
              <li key={face.generation_index} className={`face-${face.status}`}>
                d{face.sides}: <strong>{face.value}</strong> · {titleCase(face.status)}
                {face.replacement_generation_index !== null
                  ? ` by die ${face.replacement_generation_index}`
                  : ""}
              </li>
            ))}
          </ol>
        ) : <p>No dice were generated for this fixed result.</p>}
        {card.fact.adjustments.length > 0 ? (
          <ul className="roll-adjustments">
            {card.fact.adjustments.map((adjustment, index) => (
              <li key={`${adjustment.stage}:${adjustment.kind}:${index}`}>
                {adjustment.generated_face
                  ? `d${adjustment.generated_face.sides}: ${adjustment.generated_face.value} · `
                  : ""}
                {titleCase(adjustment.kind)}: {adjustment.amount > 0 ? "+" : ""}{adjustment.amount}
              </li>
            ))}
          </ul>
        ) : null}
      </details>
    </article>
  );
}
