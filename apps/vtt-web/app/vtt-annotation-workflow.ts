import {
  isLockedDrawingAnnotation,
  type AnnotationsView,
  type VttAnnotation,
} from "./vtt-annotations";

export async function clearUnlockedOwnedAnnotations(input: {
  participantId: string;
  readCurrentView: () => AnnotationsView;
  remove: (view: AnnotationsView, annotation: VttAnnotation) => Promise<void>;
}): Promise<void> {
  const initial = input.readCurrentView();
  const annotationIds = initial.annotations
    .filter(
      (annotation) =>
        annotation.author_id === input.participantId &&
        !isLockedDrawingAnnotation(annotation),
    )
    .map((annotation) => annotation.annotation_id);

  for (const annotationId of annotationIds) {
    const current = input.readCurrentView();
    const target = current.annotations.find(
      (annotation) => annotation.annotation_id === annotationId,
    );
    if (!target) continue;
    if (target.author_id !== input.participantId) {
      throw new Error(
        "An annotation owner changed while your markers were being cleared.",
      );
    }
    // Lock is intentionally checked against the freshest view immediately
    // before each awaited deletion, not only against the initial queue.
    if (isLockedDrawingAnnotation(target)) continue;
    await input.remove(current, target);
  }
}
