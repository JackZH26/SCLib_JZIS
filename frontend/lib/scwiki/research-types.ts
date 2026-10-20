export interface ResearchItem {
 id:string; paperId:string; version:string; firstRecommendedIssue:string;
 title:string; paperTitle:string; journal:string; publishedAt:string;
 publicationStatus:"journal-article"|"peer-reviewed-accepted-early-version"|"preprint"; publicationLabel:string;
 doi?:string; arxivId?:string; url:string; summary:string; whyItMatters:string; limitation:string;
 topicSlug:string; topicLabel:string; verificationScope:string; checkedAt:string; updateReason?:string; versionDate?:string;
}
export interface ResearchIssue {
 id:string; selectedAt:string; checkedAt:string; status:"published"; outcome:"selected"|"no-new-selection";
 title:string; selectionBasis:string; editorialNote:string; items:ResearchItem[];
}
export interface ResearchNotice {
 id:string; paperId:string; kind:"correction"|"retraction"|"version-update"; date:string; description:string; sourceUrl:string;
}
export interface ResearchCollection {schemaVersion:string;issues:ResearchIssue[];notices:ResearchNotice[]}
