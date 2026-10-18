export const topicGroups = [
  {id:"foundations", title:"Foundations", description:"Start with the phenomena that define a superconductor.", topics:[
    {code:"A1", label:"Zero resistance"}, {code:"A2", label:"Meissner effect"}, {code:"A6", label:"Critical fields"}, {code:"A3", label:"Specific heat"}, {code:"A4", label:"Isotope effect"}, {code:"A5", label:"Superconducting gap"}, {code:"A7", label:"Critical current"}, {code:"A9", label:"Andreev reflection"}, {code:"A10", label:"Quasiparticle interference"}, {code:"D11", label:"Two-dimensional superconductivity"},
  ]},
  {id:"materials", title:"Materials", description:"Explore the families, structures and conditions.", topics:[
    {code:"D3", label:"Cuprates"}, {code:"D4", label:"Iron-based superconductors"}, {code:"D5", label:"Nickelates"},
  ]},
  {id:"pairing", title:"Pairing & mechanisms", description:"Connect observations to models of the paired state.", topics:[
    {code:"B1", label:"BCS theory"}, {code:"B12", label:"Multiband pairing"}, {code:"C2", label:"s± pairing"}, {code:"G7", label:"Spin liquids & RVB"},
  ]},
  {id:"frontiers", title:"Properties & frontiers", description:"Follow the links between superconductivity and its wider physics.", topics:[
    {code:"F7", label:"Geometric superfluid weight"}, {code:"E4", label:"Strain engineering"}, {code:"H2", label:"Planckian dissipation"}, {code:"A8", label:"Linear-T resistivity"},
  ]},
] as const;

export function formatResearchDate(value:string) {
  return new Intl.DateTimeFormat("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(new Date(value+"T00:00:00Z"));
}
