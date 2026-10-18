import ArticlePage, {generateMetadata as articleMetadata} from "../../[slug]/page";
import {articles} from "@/lib/scwiki/catalogue";
export const dynamicParams=false;
export function generateStaticParams(){return articles().filter(a=>a.publicationKind==="open-question").map(a=>({question:a.slug.split("/")[1]}));}
type Props={params:Promise<{question:string}>};
export async function generateMetadata({params}:Props){const {question}=await params;return articleMetadata({params:Promise.resolve({slug:"open-questions/"+question})});}
export default async function QuestionPage({params}:Props){const {question}=await params;return ArticlePage({params:Promise.resolve({slug:"open-questions/"+question})});}
